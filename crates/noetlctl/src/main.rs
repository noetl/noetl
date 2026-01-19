mod config;
mod playbook_runner;

use anyhow::{Context as AnyhowContext, Result};
use base64::prelude::*;
use clap::{Parser, Subcommand};
use config::{Config, Context};
use crossterm::{
    event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::{Backend, CrosstermBackend},
    layout::{Constraint, Direction, Layout},
    widgets::{Block, Borders, List, ListItem, ListState, Paragraph},
    Frame, Terminal,
};
use reqwest::Client;
use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::PathBuf;
use std::time::{Duration, Instant};

#[derive(Parser)]
#[command(name = "noetl")]
#[command(version, about = "NoETL Command Line Tool", long_about = None)]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,

    /// Interactive mode (TUI)
    #[arg(short, long)]
    interactive: bool,

    /// NoETL server host
    #[arg(long)]
    host: Option<String>,

    /// NoETL server port
    #[arg(short, long)]
    port: Option<u16>,

    /// NoETL server URL (overrides host and port)
    #[arg(long)]
    server_url: Option<String>,
}

#[derive(Subcommand)]
enum Commands {
    /// Execute a playbook (unified command for local and distributed execution)
    ///
    /// The <ref> can be:
    ///   - A file path: ./playbooks/foo.yaml, automation/deploy.yaml
    ///   - A catalog reference: catalog://amadeus_ai_api@2.0
    ///   - A database ID: pbk_01J... (playbook ID from catalog)
    ///   - A catalog path: workflows/etl-pipeline (requires --runtime distributed)
    ///
    /// Runtime modes:
    ///   - local: Execute directly using Rust interpreter (no server required)
    ///   - distributed: Execute via NoETL server-worker architecture
    ///   - auto (default): Choose based on ref type and playbook executor.profile
    ///
    /// Examples:
    ///     noetl exec ./playbooks/http_test.yaml                    # auto runtime
    ///     noetl exec ./playbooks/http_test.yaml -r local           # force local
    ///     noetl exec catalog://amadeus_ai_api@2.0 -r distributed   # catalog + distributed
    ///     noetl exec my-playbook --runtime distributed             # catalog path
    ///     noetl exec ./foo.yaml --set key=value --verbose          # with variables
    ///     noetl exec pbk_01J... -r distributed                     # by db ID
    #[command(verbatim_doc_comment)]
    Exec {
        /// Playbook reference: file path, catalog://name@version, db ID, or catalog path
        #[arg(value_name = "REF")]
        reference: String,

        /// Runtime mode: local (Rust interpreter), distributed (server-worker), auto
        #[arg(short = 'r', long, default_value = "auto")]
        runtime: String,

        /// Target step to start execution from (local runtime only)
        #[arg(short = 't', long)]
        target: Option<String>,

        /// Set variables (format: key=value), can be repeated
        #[arg(long = "set", value_name = "KEY=VALUE")]
        variables: Vec<String>,

        /// Payload/workload as JSON string (merges with playbook workload)
        #[arg(long = "payload", value_name = "JSON", alias = "workload")]
        payload: Option<String>,

        /// Path to JSON file with input parameters
        #[arg(short, long)]
        input: Option<PathBuf>,

        /// Catalog version (for catalog:// refs without @version)
        #[arg(short = 'V', long)]
        version: Option<String>,

        /// Server endpoint for distributed runtime (default: from config)
        #[arg(long)]
        endpoint: Option<String>,

        /// Enable verbose output
        #[arg(short, long)]
        verbose: bool,

        /// Dry-run mode: validate and show plan without executing
        #[arg(long)]
        dry_run: bool,

        /// Emit only JSON response (distributed runtime)
        #[arg(short, long)]
        json: bool,
    },
    /// Alias for 'exec' - execute a playbook
    #[command(alias = "run", hide = true)]
    Run {
        /// Playbook reference: file path, catalog://name@version, db ID, or catalog path
        #[arg(value_name = "REF")]
        reference: Option<String>,

        /// Runtime mode: local (Rust interpreter), distributed (server-worker), auto
        #[arg(short = 'r', long, default_value = "auto")]
        runtime: String,

        /// Additional arguments (target step or variables)
        #[arg(trailing_var_arg = true)]
        args: Vec<String>,

        /// Set variables (format: key=value)
        #[arg(long = "set", value_name = "KEY=VALUE")]
        variables: Vec<String>,

        /// Payload/workload as JSON string
        #[arg(long = "payload", value_name = "JSON", alias = "workload")]
        payload: Option<String>,

        /// Deep merge payload with playbook workload
        #[arg(long)]
        merge: bool,

        /// Enable verbose output
        #[arg(short, long)]
        verbose: bool,
    },
    /// Context management
    Context {
        #[command(subcommand)]
        command: ContextCommand,
    },
    /// Register resources
    Register {
        #[command(subcommand)]
        resource: RegisterResource,
    },
    /// Fetch execution status (legacy command, use 'execute status' instead)
    /// Examples:
    ///     noetl status 12345
    ///     noetl --host=localhost --port=8082 status 12345 --json
    #[command(verbatim_doc_comment)]
    Status {
        /// Execution ID
        execution_id: String,

        /// Emit only the JSON response
        #[arg(short, long)]
        json: bool,
    },
    /// List resources in catalog (legacy command, use 'catalog list' instead)
    /// Examples:
    ///     noetl list Playbook
    ///     noetl list Credential --json
    ///     noetl --host=localhost --port=8082 list Playbook
    #[command(verbatim_doc_comment)]
    List {
        /// Resource type (e.g., Playbook, Credential)
        resource_type: String,

        /// Emit only the JSON response
        #[arg(short, long)]
        json: bool,
    },
    /// Catalog management
    Catalog {
        #[command(subcommand)]
        command: CatalogCommand,
    },
    /// Legacy execution management (use 'exec' instead)
    #[command(hide = true)]
    Execute {
        #[command(subcommand)]
        command: ExecuteCommand,
    },
    /// Get resource details
    Get {
        #[command(subcommand)]
        resource: GetResource,
    },
    /// Execute SQL query via NoETL Postgres API
    /// Examples:
    ///     noetl query "SELECT * FROM noetl.keychain LIMIT 5"
    ///     noetl query "SELECT * FROM noetl.keychain WHERE execution_id = 123" --schema noetl
    ///     noetl query "SELECT * FROM my_table" --format json
    ///     noetl query "SELECT * FROM users" --schema public --format table
    #[command(verbatim_doc_comment)]
    Query {
        /// SQL query to execute
        query: String,

        /// Database schema (default: noetl)
        #[arg(short, long, default_value = "noetl")]
        schema: String,

        /// Output format: table or json
        #[arg(short, long, default_value = "table")]
        format: String,
    },
    /// Server management
    /// Examples:
    ///     noetl server start
    ///     noetl server start --init-db
    ///     noetl server stop
    ///     noetl server stop --force
    #[command(verbatim_doc_comment)]
    Server {
        #[command(subcommand)]
        command: ServerCommand,
    },
    /// Worker management
    /// Examples:
    ///     noetl worker start
    ///     noetl worker start --max-workers 4
    ///     noetl worker stop
    ///     noetl worker stop --name my-worker --force
    #[command(verbatim_doc_comment)]
    Worker {
        #[command(subcommand)]
        command: WorkerCommand,
    },
    /// Database management
    /// Examples:
    ///     noetl db init
    ///     noetl db validate
    #[command(verbatim_doc_comment)]
    Db {
        #[command(subcommand)]
        command: DbCommand,
    },
    /// Build Docker images
    /// Examples:
    ///     noetl build
    ///     noetl build --no-cache
    ///     noetl build --platform linux/arm64
    #[command(verbatim_doc_comment)]
    Build {
        /// Build without cache
        #[arg(long)]
        no_cache: bool,

        /// Target platform for the Docker image (e.g., linux/amd64, linux/arm64)
        #[arg(long, default_value = "linux/amd64")]
        platform: String,
    },
    /// Kubernetes deployment management
    /// Examples:
    ///     noetl k8s deploy
    ///     noetl k8s redeploy
    ///     noetl k8s reset
    ///     noetl k8s remove
    #[command(verbatim_doc_comment)]
    K8s {
        #[command(subcommand)]
        command: K8sCommand,
    },
    /// Infrastructure as Playbook (IaP) - manage cloud infrastructure using playbooks
    /// 
    /// IaP provides Terraform-like infrastructure management using NoETL playbooks.
    /// State is stored locally in DuckDB and can be synced to GCS for team collaboration.
    /// 
    /// Examples:
    ///     noetl iap init --project my-gcp-project --bucket my-state-bucket
    ///     noetl iap plan infrastructure.yaml
    ///     noetl iap apply infrastructure.yaml
    ///     noetl iap state list
    ///     noetl iap sync push
    ///     noetl iap drift detect
    #[command(verbatim_doc_comment)]
    Iap {
        #[command(subcommand)]
        command: IapCommand,
    },
}

#[derive(Subcommand)]
enum CatalogCommand {
    /// Register a resource (auto-detects type)
    /// Example for playbooks:
    ///     noetl catalog register tests/fixtures/playbooks/hello_world/hello_world.yaml
    ///     noetl --host=localhost --port=8082 catalog register tests/fixtures/playbooks/hello_world/hello_world.yaml
    /// Example for credential:
    ///     noetl --host=localhost --port=8082 catalog register tests/fixtures/credentials/google_oauth.json
    #[command(verbatim_doc_comment)]
    Register {
        /// Path to the resource file
        file: PathBuf,
    },
    /// Get resource details from catalog
    /// Examples:
    ///     noetl catalog get my-playbook
    ///     noetl --host=localhost --port=8082 catalog get workflows/data-pipeline
    ///     noetl catalog get my-credential
    #[command(verbatim_doc_comment)]
    Get {
        /// Resource path/name
        path: String,
    },
    /// List resources in catalog by type
    /// Examples:
    ///     noetl catalog list Playbook
    ///     noetl catalog list Credential
    ///     noetl --host=localhost --port=8082 catalog list Playbook --json
    #[command(verbatim_doc_comment)]
    List {
        /// Resource type (e.g., Playbook, Credential)
        resource_type: String,

        /// Emit only the JSON response
        #[arg(short, long)]
        json: bool,
    },
}

#[derive(Subcommand)]
enum ExecuteCommand {
    /// Execute a playbook with optional input parameters
    /// Examples:
    ///     noetl execute playbook my-playbook
    ///     noetl execute playbook workflows/etl-pipeline --input params.json
    ///     noetl --host=localhost --port=8082 execute playbook data-sync --input /path/to/input.json --json
    #[command(verbatim_doc_comment)]
    Playbook {
        /// Playbook path/name as registered in catalog
        path: String,

        /// Path to JSON file with parameters
        #[arg(short, long)]
        input: Option<PathBuf>,

        /// Emit only the JSON response
        #[arg(short, long)]
        json: bool,
    },
    /// Get execution status for a playbook run
    /// Examples:
    ///     noetl execute status 12345
    ///     noetl --host=localhost --port=8082 execute status 12345 --json
    #[command(verbatim_doc_comment)]
    Status {
        /// Execution ID
        execution_id: String,

        /// Emit only the JSON response
        #[arg(short, long)]
        json: bool,
    },
}

#[derive(Subcommand)]
enum GetResource {
    /// Get credential details with optional data inclusion
    /// Examples:
    ///     noetl get credential my-db-creds
    ///     noetl get credential google_oauth --include_data=false
    ///     noetl --host=localhost --port=8082 get credential aws-credentials
    #[command(verbatim_doc_comment)]
    Credential {
        /// Name of the credential
        name: String,

        /// Include decrypted data
        #[arg(long, default_value_t = true)]
        include_data: bool,
    },
}

#[derive(Subcommand)]
enum RegisterResource {
    /// Register credential(s) from JSON file or directory
    /// Examples:
    ///     noetl register credential --file credentials/postgres.json
    ///     noetl register credential --directory tests/fixtures/credentials
    ///     noetl --host=localhost --port=8082 register credential -f tests/fixtures/credentials/google_oauth.json
    #[command(verbatim_doc_comment)]
    Credential {
        /// Path to credential file
        #[arg(short, long, conflicts_with = "directory")]
        file: Option<PathBuf>,

        /// Path to directory containing credential JSON files (scans recursively)
        #[arg(short, long, conflicts_with = "file")]
        directory: Option<PathBuf>,
    },
    /// Register playbook(s) from YAML file or directory
    /// Examples:
    ///     noetl register playbook --file playbooks/my-workflow.yaml
    ///     noetl register playbook --directory tests/fixtures/playbooks
    ///     noetl --host=localhost --port=8082 register playbook -f tests/fixtures/playbooks/hello_world/hello_world.yaml
    #[command(verbatim_doc_comment)]
    Playbook {
        /// Path to playbook file
        #[arg(short, long, conflicts_with = "directory")]
        file: Option<PathBuf>,

        /// Path to directory containing playbook YAML files (scans recursively)
        #[arg(short, long, conflicts_with = "file")]
        directory: Option<PathBuf>,
    },
}

#[derive(Subcommand)]
enum ServerCommand {
    /// Start NoETL server
    /// Examples:
    ///     noetl server start
    ///     noetl server start --init-db
    #[command(verbatim_doc_comment)]
    Start {
        /// Initialize database schema on startup
        #[arg(long)]
        init_db: bool,
    },
    /// Stop NoETL server
    /// Examples:
    ///     noetl server stop
    ///     noetl server stop --force
    #[command(verbatim_doc_comment)]
    Stop {
        /// Force stop without confirmation
        #[arg(short, long)]
        force: bool,
    },
}

#[derive(Subcommand)]
enum WorkerCommand {
    /// Start NoETL worker pool
    /// Examples:
    ///     noetl worker start
    ///     noetl worker start --max-workers 4
    #[command(verbatim_doc_comment)]
    Start {
        /// Maximum number of worker threads
        #[arg(short = 'm', long)]
        max_workers: Option<usize>,
    },
    /// Stop NoETL worker
    /// Examples:
    ///     noetl worker stop
    ///     noetl worker stop --name my-worker
    ///     noetl worker stop --name my-worker --force
    #[command(verbatim_doc_comment)]
    Stop {
        /// Worker name to stop (if not specified, lists all workers)
        #[arg(short = 'n', long)]
        name: Option<String>,

        /// Force stop without confirmation
        #[arg(short, long)]
        force: bool,
    },
}

#[derive(Subcommand)]
enum DbCommand {
    /// Initialize NoETL database schema
    /// Example:
    ///     noetl db init
    #[command(verbatim_doc_comment)]
    Init,
    /// Validate NoETL database schema
    /// Example:
    ///     noetl db validate
    #[command(verbatim_doc_comment)]
    Validate,
}

#[derive(Subcommand)]
enum K8sCommand {
    /// Deploy NoETL to Kubernetes (kind cluster)
    /// Example:
    ///     noetl k8s deploy
    #[command(verbatim_doc_comment)]
    Deploy,
    /// Remove NoETL from Kubernetes
    /// Example:
    ///     noetl k8s remove
    #[command(verbatim_doc_comment)]
    Remove,
    /// Rebuild and redeploy NoETL to Kubernetes
    /// Example:
    ///     noetl k8s redeploy
    ///     noetl k8s redeploy --no-cache
    ///     noetl k8s redeploy --platform linux/arm64
    #[command(verbatim_doc_comment)]
    Redeploy {
        /// Build without cache
        #[arg(long)]
        no_cache: bool,

        /// Target platform for the Docker image (e.g., linux/amd64, linux/arm64)
        #[arg(long, default_value = "linux/amd64")]
        platform: String,
    },
    /// Reset NoETL: rebuild, redeploy, reset schema, and setup test environment
    /// Example:
    ///     noetl k8s reset
    ///     noetl k8s reset --no-cache
    ///     noetl k8s reset --platform linux/arm64
    #[command(verbatim_doc_comment)]
    Reset {
        /// Build without cache
        #[arg(long)]
        no_cache: bool,

        /// Target platform for the Docker image (e.g., linux/amd64, linux/arm64)
        #[arg(long, default_value = "linux/amd64")]
        platform: String,
    },
}

#[derive(Subcommand)]
enum IapCommand {
    /// Initialize IaP state for a project
    /// 
    /// Creates local DuckDB state database and optionally configures GCS sync.
    /// 
    /// Examples:
    ///     noetl iap init --project my-gcp-project
    ///     noetl iap init --project my-gcp-project --bucket my-state-bucket
    ///     noetl iap init --project my-gcp-project --region us-central1
    #[command(verbatim_doc_comment)]
    Init {
        /// GCP project ID
        #[arg(long)]
        project: String,

        /// GCS bucket for remote state (optional)
        #[arg(long)]
        bucket: Option<String>,

        /// GCP region (default: us-central1)
        #[arg(long, default_value = "us-central1")]
        region: String,

        /// Local state database path (default: .noetl/state.duckdb)
        #[arg(long, default_value = ".noetl/state.duckdb")]
        state_db: String,

        /// Workspace name for state isolation (default: default)
        #[arg(long, default_value = "default")]
        workspace: String,

        /// Remote state path template (use {workspace} placeholder)
        /// Example: workspaces/{workspace}/state.duckdb
        #[arg(long, default_value = "workspaces/{workspace}/state.duckdb")]
        state_path: String,
    },
    /// Plan infrastructure changes (dry-run)
    /// 
    /// Executes the playbook in plan mode, showing what changes would be made.
    /// 
    /// Examples:
    ///     noetl iap plan infrastructure.yaml
    ///     noetl iap plan gke_autopilot.yaml --var cluster_name=my-cluster
    #[command(verbatim_doc_comment)]
    Plan {
        /// Path to infrastructure playbook
        playbook: PathBuf,

        /// Set variables (format: key=value)
        #[arg(long = "var", value_name = "KEY=VALUE")]
        variables: Vec<String>,

        /// Enable verbose output
        #[arg(short, long)]
        verbose: bool,
    },
    /// Apply infrastructure changes
    /// 
    /// Executes the playbook and records state changes.
    /// 
    /// Examples:
    ///     noetl iap apply infrastructure.yaml
    ///     noetl iap apply gke_autopilot.yaml --var cluster_name=my-cluster
    ///     noetl iap apply infrastructure.yaml --auto-approve
    #[command(verbatim_doc_comment)]
    Apply {
        /// Path to infrastructure playbook
        playbook: PathBuf,

        /// Set variables (format: key=value)
        #[arg(long = "var", value_name = "KEY=VALUE")]
        variables: Vec<String>,

        /// Skip confirmation prompt
        #[arg(long)]
        auto_approve: bool,

        /// Enable verbose output
        #[arg(short, long)]
        verbose: bool,
    },
    /// Manage infrastructure state
    /// 
    /// View, inspect, or modify the local state database.
    #[command(verbatim_doc_comment)]
    State {
        #[command(subcommand)]
        command: IapStateCommand,
    },
    /// Sync state with remote storage (GCS)
    /// 
    /// Push or pull state to/from GCS for team collaboration.
    #[command(verbatim_doc_comment)]
    Sync {
        #[command(subcommand)]
        command: IapSyncCommand,
    },
    /// Detect configuration drift
    /// 
    /// Compare current infrastructure state with actual cloud resources.
    /// 
    /// Examples:
    ///     noetl iap drift detect
    ///     noetl iap drift detect --resource gke-cluster/my-cluster
    #[command(verbatim_doc_comment)]
    Drift {
        #[command(subcommand)]
        command: IapDriftCommand,
    },
    /// Manage workspaces for multi-developer collaboration
    /// 
    /// Workspaces isolate state for different environments or developers.
    /// 
    /// Examples:
    ///     noetl iap workspace list
    ///     noetl iap workspace switch staging
    ///     noetl iap workspace create dev-alice
    #[command(verbatim_doc_comment)]
    Workspace {
        #[command(subcommand)]
        command: IapWorkspaceCommand,
    },
}

#[derive(Subcommand)]
enum IapStateCommand {
    /// List all resources in state
    /// Example:
    ///     noetl iap state list
    #[command(verbatim_doc_comment)]
    List {
        /// Filter by resource type (e.g., gke-cluster, gcs-bucket)
        #[arg(long)]
        resource_type: Option<String>,

        /// Output format: table or json
        #[arg(short, long, default_value = "table")]
        format: String,
    },
    /// Show details for a specific resource
    /// Example:
    ///     noetl iap state show gke-cluster/my-cluster
    #[command(verbatim_doc_comment)]
    Show {
        /// Resource identifier (type/name)
        resource: String,
    },
    /// Remove a resource from state (does not destroy the actual resource)
    /// Example:
    ///     noetl iap state rm gke-cluster/my-cluster
    #[command(verbatim_doc_comment)]
    Rm {
        /// Resource identifier (type/name)
        resource: String,

        /// Skip confirmation prompt
        #[arg(long)]
        force: bool,
    },
    /// Execute raw SQL query against state database
    /// Example:
    ///     noetl iap state query "SELECT * FROM resources WHERE status = 'active'"
    #[command(verbatim_doc_comment)]
    Query {
        /// SQL query to execute
        sql: String,
    },
}

#[derive(Subcommand)]
enum IapSyncCommand {
    /// Push local state to GCS
    /// Example:
    ///     noetl iap sync push
    #[command(verbatim_doc_comment)]
    Push {
        /// Skip confirmation prompt
        #[arg(long)]
        force: bool,
    },
    /// Pull state from GCS to local
    /// Example:
    ///     noetl iap sync pull
    #[command(verbatim_doc_comment)]
    Pull {
        /// Skip confirmation prompt
        #[arg(long)]
        force: bool,
    },
    /// Show sync status (local vs remote)
    /// Example:
    ///     noetl iap sync status
    #[command(verbatim_doc_comment)]
    Status,
}

#[derive(Subcommand)]
enum IapDriftCommand {
    /// Detect drift between state and actual resources
    /// Example:
    ///     noetl iap drift detect
    #[command(verbatim_doc_comment)]
    Detect {
        /// Filter by resource type
        #[arg(long)]
        resource_type: Option<String>,

        /// Specific resource to check
        #[arg(long)]
        resource: Option<String>,
    },
    /// Show drift report
    /// Example:
    ///     noetl iap drift report
    #[command(verbatim_doc_comment)]
    Report {
        /// Output format: table or json
        #[arg(short, long, default_value = "table")]
        format: String,
    },
}

#[derive(Subcommand)]
enum IapWorkspaceCommand {
    /// List all registered workspaces
    /// Shows both local registry and remote workspaces from GCS
    /// Example:
    ///     noetl iap workspace list
    ///     noetl iap workspace list --remote
    #[command(verbatim_doc_comment)]
    List {
        /// Include remote workspaces from GCS
        #[arg(long)]
        remote: bool,
    },
    /// Switch to a different workspace
    /// Updates local state to use the specified workspace
    /// Example:
    ///     noetl iap workspace switch staging
    ///     noetl iap workspace switch dev-alice --pull
    #[command(verbatim_doc_comment)]
    Switch {
        /// Workspace name to switch to
        name: String,

        /// Pull state from remote after switching
        #[arg(long)]
        pull: bool,
    },
    /// Show current workspace info
    /// Example:
    ///     noetl iap workspace current
    #[command(verbatim_doc_comment)]
    Current,
    /// Create a new workspace
    /// Example:
    ///     noetl iap workspace create dev-bob
    ///     noetl iap workspace create dev-charlie --from staging
    #[command(verbatim_doc_comment)]
    Create {
        /// New workspace name
        name: String,

        /// Clone state from existing workspace
        #[arg(long)]
        from: Option<String>,

        /// Switch to new workspace after creation
        #[arg(long)]
        switch: bool,
    },
    /// Delete a workspace from registry (does not delete remote state)
    /// Example:
    ///     noetl iap workspace delete dev-old
    #[command(verbatim_doc_comment)]
    Delete {
        /// Workspace name to delete
        name: String,

        /// Also delete remote state from GCS
        #[arg(long)]
        remote: bool,

        /// Skip confirmation prompt
        #[arg(long)]
        force: bool,
    },
}

#[derive(Subcommand)]
enum ContextCommand {
    /// Add a new context for connecting to NoETL servers
    /// Examples:
    ///     noetl context add local --server-url=http://localhost:8082
    ///     noetl context add local-dev --server-url=http://localhost:8082 --runtime=local
    ///     noetl context add prod --server-url=https://noetl.example.com --runtime=distributed
    ///     noetl context add staging --server-url=http://staging:8082 --set-current
    #[command(verbatim_doc_comment)]
    Add {
        /// Context name
        name: String,
        /// Server URL (e.g., http://localhost:8082)
        #[arg(long)]
        server_url: String,
        /// Default runtime mode for this context: local, distributed, or auto
        #[arg(long, default_value = "auto")]
        runtime: String,
        /// Set as current context
        #[arg(long)]
        set_current: bool,
    },
    /// List all configured contexts
    /// Example:
    ///     noetl context list
    #[command(verbatim_doc_comment)]
    List,
    /// Switch to a different context
    /// Examples:
    ///     noetl context use local
    ///     noetl context use prod
    #[command(verbatim_doc_comment)]
    Use {
        /// Context name to switch to
        name: String,
    },
    /// Set runtime mode for current context
    /// Examples:
    ///     noetl context set-runtime local
    ///     noetl context set-runtime distributed
    ///     noetl context set-runtime auto
    #[command(verbatim_doc_comment)]
    SetRuntime {
        /// Runtime mode: local, distributed, or auto
        runtime: String,
    },
    /// Delete a context
    /// Examples:
    ///     noetl context delete old-env
    ///     noetl context delete staging
    #[command(verbatim_doc_comment)]
    Delete {
        /// Context name to delete
        name: String,
    },
    /// Show current active context
    /// Example:
    ///     noetl context current
    #[command(verbatim_doc_comment)]
    Current,
}

#[derive(Serialize)]
struct RegisterRequest {
    content: String,
    resource_type: String,
}

/// Reference type for playbook execution
#[derive(Debug)]
enum RefType {
    /// Local file path: ./playbooks/foo.yaml
    File(PathBuf),
    /// Catalog reference: catalog://name@version
    Catalog { name: String, version: Option<String> },
    /// Database ID: pbk_01J...
    DatabaseId(String),
    /// Catalog path (requires distributed): workflows/etl-pipeline
    CatalogPath(String),
}

/// Execution context parsed from reference
#[derive(Debug)]
struct ExecContext {
    ref_type: RefType,
    version: Option<String>,
}

/// Parse execution reference into type and metadata
fn parse_exec_reference(reference: &str, version_override: Option<&str>) -> Result<ExecContext> {
    // Pattern 1: catalog://name@version
    if reference.starts_with("catalog://") {
        let rest = reference.strip_prefix("catalog://").unwrap();
        let (name, version) = if let Some(at_pos) = rest.find('@') {
            (rest[..at_pos].to_string(), Some(rest[at_pos + 1..].to_string()))
        } else {
            (rest.to_string(), version_override.map(|s| s.to_string()))
        };
        return Ok(ExecContext {
            ref_type: RefType::Catalog { name, version: version.clone() },
            version,
        });
    }
    
    // Pattern 2: Database ID (pbk_xxx or similar UUID-like)
    if reference.starts_with("pbk_") || 
       (reference.len() > 20 && reference.chars().all(|c| c.is_alphanumeric() || c == '_' || c == '-')) {
        return Ok(ExecContext {
            ref_type: RefType::DatabaseId(reference.to_string()),
            version: version_override.map(|s| s.to_string()),
        });
    }
    
    // Pattern 3: File path (contains / or \ or ends with .yaml/.yml or file exists)
    let is_file_like = reference.contains('/') || 
                       reference.contains('\\') || 
                       reference.ends_with(".yaml") || 
                       reference.ends_with(".yml");
    
    if is_file_like {
        let path = PathBuf::from(reference);
        if path.exists() || reference.ends_with(".yaml") || reference.ends_with(".yml") {
            return Ok(ExecContext {
                ref_type: RefType::File(path),
                version: None,
            });
        }
    }
    
    // Try to find as file with extension
    let try_find_file = |base: &str| -> Option<PathBuf> {
        let path = PathBuf::from(base);
        if path.exists() && path.is_file() {
            return Some(path);
        }
        let yaml_path = PathBuf::from(format!("{}.yaml", base));
        if yaml_path.exists() && yaml_path.is_file() {
            return Some(yaml_path);
        }
        let yml_path = PathBuf::from(format!("{}.yml", base));
        if yml_path.exists() && yml_path.is_file() {
            return Some(yml_path);
        }
        None
    };
    
    if let Some(file_path) = try_find_file(reference) {
        return Ok(ExecContext {
            ref_type: RefType::File(file_path),
            version: None,
        });
    }
    
    // Pattern 4: Catalog path (no file found, assume it's a catalog reference)
    Ok(ExecContext {
        ref_type: RefType::CatalogPath(reference.to_string()),
        version: version_override.map(|s| s.to_string()),
    })
}

/// Resolve runtime mode based on:
/// 1. CLI flag (--runtime local|distributed) - highest priority if explicitly set
/// 2. If --runtime auto (default): use context config runtime preference
/// 3. If context runtime is also auto: auto-detect from reference type
fn resolve_runtime(
    runtime_flag: &str, 
    context_runtime: Option<&str>,
    ctx: &ExecContext, 
    verbose: bool
) -> Result<String> {
    // CLI flag takes precedence if explicitly set (not "auto")
    if runtime_flag != "auto" {
        if verbose {
            println!("Runtime: {} (from --runtime flag)", runtime_flag);
        }
        return Ok(runtime_flag.to_string());
    }
    
    // --runtime auto (default): check context config preference
    if let Some(ctx_runtime) = context_runtime {
        if ctx_runtime != "auto" {
            if verbose {
                println!("Runtime: {} (from context config)", ctx_runtime);
            }
            return Ok(ctx_runtime.to_string());
        }
    }
    
    // Context runtime is also "auto": auto-resolve based on reference type
    let resolved = match &ctx.ref_type {
        RefType::File(_) => "local",
        RefType::Catalog { .. } => "distributed",
        RefType::DatabaseId(_) => "distributed",
        RefType::CatalogPath(_) => "distributed",
    };
    if verbose {
        println!("Runtime: {} (auto-detected from reference type)", resolved);
    }
    Ok(resolved.to_string())
}

/// Build variables map from payload JSON and --set flags
fn build_variables(
    payload: Option<&str>, 
    variables: &[String]
) -> Result<HashMap<String, String>> {
    let mut vars = HashMap::new();
    
    // Parse payload JSON if provided
    if let Some(payload_str) = payload {
        match serde_json::from_str::<serde_json::Value>(payload_str) {
            Ok(serde_json::Value::Object(map)) => {
                for (key, value) in map {
                    let value_str = match value {
                        serde_json::Value::String(s) => s,
                        serde_json::Value::Number(n) => n.to_string(),
                        serde_json::Value::Bool(b) => b.to_string(),
                        serde_json::Value::Null => "null".to_string(),
                        other => serde_json::to_string(&other).unwrap_or_else(|_| "null".to_string()),
                    };
                    vars.insert(key, value_str);
                }
            }
            Ok(_) => {
                eprintln!("Error: Payload must be a JSON object, not array or primitive");
                std::process::exit(1);
            }
            Err(e) => {
                eprintln!("Error: Invalid JSON payload: {}", e);
                std::process::exit(1);
            }
        }
    }
    
    // Parse --set variables (override payload)
    for var in variables {
        let parts: Vec<&str> = var.splitn(2, '=').collect();
        if parts.len() == 2 {
            vars.insert(parts[0].to_string(), parts[1].to_string());
        } else {
            eprintln!("Warning: Invalid variable format '{}', expected key=value", var);
        }
    }
    
    Ok(vars)
}

/// Resolve playbook file path and optional target step
/// Implements File-First Strategy:
/// 1. Check if first arg is explicit path (contains / or \ or ends with .yaml/.yml)
/// 2. Check if file exists (as-is, with .yaml, with .yml)
/// 3. Auto-discover: ./noetl.yaml (priority) → ./main.yaml (fallback)
/// 4. Treat remaining args as target step
fn resolve_playbook_and_target(
    playbook_or_target: Option<String>,
    args: Vec<String>,
) -> Result<(PathBuf, Option<String>)> {
    // Helper: Check if string looks like a file path
    let is_explicit_path =
        |s: &str| -> bool { s.contains('/') || s.contains('\\') || s.ends_with(".yaml") || s.ends_with(".yml") };

    // Helper: Try to find file with extensions
    let try_find_file = |base: &str| -> Option<PathBuf> {
        // Try as-is
        let path = PathBuf::from(base);
        if path.exists() && path.is_file() {
            return Some(path);
        }

        // Try with .yaml extension
        let yaml_path = PathBuf::from(format!("{}.yaml", base));
        if yaml_path.exists() && yaml_path.is_file() {
            return Some(yaml_path);
        }

        // Try with .yml extension
        let yml_path = PathBuf::from(format!("{}.yml", base));
        if yml_path.exists() && yml_path.is_file() {
            return Some(yml_path);
        }

        None
    };

    // Helper: Auto-discover playbook in current directory
    let auto_discover = || -> Result<PathBuf> {
        // Priority 1: noetl.yaml
        if let Some(path) = try_find_file("./noetl") {
            return Ok(path);
        }

        // Priority 2: main.yaml
        if let Some(path) = try_find_file("./main") {
            return Ok(path);
        }

        // No playbook found
        anyhow::bail!(
            "No playbook found. Expected ./noetl.yaml or ./main.yaml in current directory.\n\
             Hint: Specify explicit path like: noetl run automation/main.yaml"
        )
    };

    // Case 1: No first arg provided → auto-discover, first trailing arg is target
    if playbook_or_target.is_none() {
        let playbook = auto_discover()?;
        let target = args.first().map(|s| s.to_string());
        return Ok((playbook, target));
    }

    let first_arg = playbook_or_target.unwrap();

    // Case 2: First arg is explicit path → use it, first trailing arg is target
    if is_explicit_path(&first_arg) {
        let playbook = PathBuf::from(&first_arg);
        if !playbook.exists() {
            anyhow::bail!("Playbook file not found: {}", playbook.display());
        }
        let target = args.first().map(|s| s.to_string());
        return Ok((playbook, target));
    }

    // Case 3: First arg might be a file (without extension) → check if exists
    if let Some(playbook) = try_find_file(&first_arg) {
        // File found! First trailing arg is target
        let target = args.first().map(|s| s.to_string());
        return Ok((playbook, target));
    }

    // Case 4: First arg is not a file → auto-discover, first arg is target
    let playbook = auto_discover()?;
    let target = Some(first_arg);
    Ok((playbook, target))
}

#[tokio::main]
async fn main() -> Result<()> {
    let cli = Cli::parse();
    let mut config = Config::load()?;

    let base_url = if let Some(url) = cli.server_url {
        url
    } else if let (Some(host), Some(port)) = (cli.host.as_ref(), cli.port) {
        format!("http://{}:{}", host, port)
    } else {
        config
            .get_current_context()
            .map(|(_, ctx)| ctx.server_url.clone())
            .unwrap_or_else(|| "http://localhost:8082".to_string())
    };

    if cli.interactive {
        return run_tui(&base_url).await;
    }

    let client = Client::new();

    match cli.command {
        Some(Commands::Exec {
            reference,
            runtime,
            target,
            variables,
            payload,
            input,
            version,
            endpoint,
            verbose,
            dry_run,
            json,
        }) => {
            // Get context runtime preference
            let context_runtime = config.get_current_context()
                .map(|(_, ctx)| ctx.runtime.as_str());
            
            // Parse the reference to determine type and resolve runtime
            let exec_ctx = parse_exec_reference(&reference, version.as_deref())?;
            let effective_runtime = resolve_runtime(&runtime, context_runtime, &exec_ctx, verbose)?;
            let effective_endpoint = endpoint.unwrap_or_else(|| base_url.clone());
            
            // Build variables from payload and --set flags
            let vars = build_variables(payload.as_deref(), &variables)?;
            
            // Load variables from input file if provided (used in distributed mode)
            let _input_payload = if let Some(input_file) = &input {
                let content = fs::read_to_string(input_file)
                    .context(format!("Failed to read input file: {:?}", input_file))?;
                Some(serde_json::from_str::<serde_json::Value>(&content)
                    .context("Failed to parse input JSON")?)
            } else {
                None
            };
            
            if verbose {
                println!("Execution Context:");
                println!("  Reference: {}", reference);
                println!("  Type: {:?}", exec_ctx.ref_type);
                println!("  Runtime: {}", effective_runtime);
                if let Some(v) = &exec_ctx.version {
                    println!("  Version: {}", v);
                }
                if let Some(t) = &target {
                    println!("  Target: {}", t);
                }
            }
            
            if dry_run {
                println!("\n[DRY RUN] Would execute with:");
                println!("  Runtime: {}", effective_runtime);
                match &exec_ctx.ref_type {
                    RefType::File(path) => println!("  File: {}", path.display()),
                    RefType::Catalog { name, version } => {
                        println!("  Catalog: {}", name);
                        if let Some(v) = version {
                            println!("  Version: {}", v);
                        }
                    }
                    RefType::DatabaseId(id) => println!("  DB ID: {}", id),
                    RefType::CatalogPath(path) => println!("  Path: {}", path),
                }
                return Ok(());
            }
            
            match effective_runtime.as_str() {
                "local" => {
                    // Local execution using Rust interpreter
                    let playbook_path = match &exec_ctx.ref_type {
                        RefType::File(path) => path.clone(),
                        RefType::Catalog { .. } | RefType::DatabaseId(_) | RefType::CatalogPath(_) => {
                            eprintln!("Error: Local runtime requires a file path reference");
                            eprintln!("  Use: noetl exec ./path/to/playbook.yaml -r local");
                            eprintln!("  Or use: -r distributed for catalog/db references");
                            std::process::exit(1);
                        }
                    };
                    
                    let runner = playbook_runner::PlaybookRunner::new(playbook_path)
                        .with_variables(vars)
                        .with_verbose(verbose)
                        .with_target(target);
                    
                    runner.run()?;
                }
                "distributed" => {
                    // Distributed execution via server
                    let (path, version) = match &exec_ctx.ref_type {
                        RefType::File(file_path) => {
                            // For file refs, we need to register first or use a different approach
                            eprintln!("Warning: Executing local file via distributed runtime");
                            eprintln!("  Consider registering with: noetl catalog register {}", file_path.display());
                            // Use filename as path for now
                            let name = file_path.file_stem()
                                .map(|s| s.to_string_lossy().to_string())
                                .unwrap_or_else(|| "playbook".to_string());
                            (name, None)
                        }
                        RefType::Catalog { name, version } => {
                            (name.clone(), version.clone())
                        }
                        RefType::DatabaseId(id) => {
                            (id.clone(), None) // Server handles ID lookup
                        }
                        RefType::CatalogPath(path) => {
                            (path.clone(), exec_ctx.version.clone())
                        }
                    };
                    
                    execute_playbook_distributed(
                        &client, 
                        &effective_endpoint, 
                        &path, 
                        version.and_then(|v| v.parse().ok()), 
                        input, 
                        json
                    ).await?;
                }
                _ => {
                    eprintln!("Error: Unknown runtime '{}'. Use: local, distributed, or auto", effective_runtime);
                    std::process::exit(1);
                }
            }
        }
        Some(Commands::Run {
            reference,
            runtime,
            args,
            variables,
            payload,
            merge,
            verbose,
        }) => {
            // Get context runtime preference
            let context_runtime = config.get_current_context()
                .map(|(_, ctx)| ctx.runtime.as_str());
            
            // Determine effective runtime (context takes precedence for "auto")
            let effective_runtime = if runtime == "auto" {
                context_runtime.unwrap_or("local")
            } else {
                &runtime
            };
            
            // Build variables
            let vars = build_variables(payload.as_deref(), &variables)?;
            
            if effective_runtime == "distributed" {
                // Distributed execution via server
                let catalog_path = if let Some(ref_str) = &reference {
                    // Use the reference as catalog path
                    // Strip .yaml/.yml extension if present for catalog lookup
                    ref_str
                        .trim_end_matches(".yaml")
                        .trim_end_matches(".yml")
                        .to_string()
                } else {
                    eprintln!("Error: Playbook reference required for distributed execution");
                    std::process::exit(1);
                };
                
                if verbose {
                    println!("Catalog path: {}", catalog_path);
                    println!("Runtime: {}", effective_runtime);
                    println!("Server: {}", base_url);
                }
                
                execute_playbook_distributed(
                    &client, 
                    &base_url, 
                    &catalog_path, 
                    None, // version
                    None, // input file
                    false // json output
                ).await?;
            } else {
                // Local execution - resolve playbook file
                let (playbook_path, target) = if let Some(ref_str) = reference {
                    resolve_playbook_and_target(Some(ref_str), args)?
                } else {
                    resolve_playbook_and_target(None, args)?
                };
                
                if verbose {
                    println!("Resolved playbook: {}", playbook_path.display());
                    if let Some(ref t) = target {
                        println!("Target: {}", t);
                    }
                    println!("Runtime: {}", effective_runtime);
                }
                
                let runner = playbook_runner::PlaybookRunner::new(playbook_path)
                    .with_variables(vars)
                    .with_merge(merge)
                    .with_verbose(verbose)
                    .with_target(target);
                
                runner.run()?;
            }
        }
        Some(Commands::Context { command }) => {
            handle_context_command(&mut config, command)?;
        }
        Some(Commands::Register { resource }) => match resource {
            RegisterResource::Credential { file, directory } => {
                if let Some(f) = file {
                    register_resource(&client, &base_url, "Credential", &f).await?;
                } else if let Some(d) = directory {
                    register_directory(&client, &base_url, "Credential", &d, &["json"]).await?;
                } else {
                    eprintln!("Error: Either --file or --directory must be specified");
                    std::process::exit(1);
                }
            }
            RegisterResource::Playbook { file, directory } => {
                if let Some(f) = file {
                    register_resource(&client, &base_url, "Playbook", &f).await?;
                } else if let Some(d) = directory {
                    register_directory(&client, &base_url, "Playbook", &d, &["yaml", "yml"]).await?;
                } else {
                    eprintln!("Error: Either --file or --directory must be specified");
                    std::process::exit(1);
                }
            }
        },
        Some(Commands::Status { execution_id, json }) => {
            get_status(&client, &base_url, &execution_id, json).await?;
        }
        Some(Commands::List { resource_type, json }) => {
            list_resources(&client, &base_url, &resource_type, json).await?;
        }
        Some(Commands::Catalog { command }) => {
            match command {
                CatalogCommand::Register { file } => {
                    // Auto-detect type from file content
                    let content =
                        fs::read_to_string(&file).context(format!("Failed to read file: {:?}", file.display()))?;
                    let resource_type = if content.contains("kind: Credential") {
                        "Credential"
                    } else if content.contains("kind: Playbook") {
                        "Playbook"
                    } else {
                        "Playbook" // Default
                    };
                    register_resource(&client, &base_url, resource_type, &file).await?;
                }
                CatalogCommand::Get { path } => {
                    get_catalog_resource(&client, &base_url, &path).await?;
                }
                CatalogCommand::List { resource_type, json } => {
                    list_resources(&client, &base_url, &resource_type, json).await?;
                }
            }
        }
        Some(Commands::Execute { command }) => match command {
            ExecuteCommand::Playbook { path, input, json } => {
                execute_playbook(&client, &base_url, &path, input, json).await?;
            }
            ExecuteCommand::Status { execution_id, json } => {
                get_status(&client, &base_url, &execution_id, json).await?;
            }
        },
        Some(Commands::Get { resource }) => match resource {
            GetResource::Credential { name, include_data } => {
                get_credential(&client, &base_url, &name, include_data).await?;
            }
        },
        Some(Commands::Query { query, schema, format }) => {
            execute_query(&client, &base_url, &query, &schema, &format).await?;
        }
        Some(Commands::Server { command }) => match command {
            ServerCommand::Start { init_db } => {
                start_server(init_db).await?;
            }
            ServerCommand::Stop { force } => {
                stop_server(force).await?;
            }
        },
        Some(Commands::Worker { command }) => match command {
            WorkerCommand::Start { max_workers } => {
                start_worker(max_workers).await?;
            }
            WorkerCommand::Stop { name, force } => {
                stop_worker(name, force).await?;
            }
        },
        Some(Commands::Db { command }) => match command {
            DbCommand::Init => {
                db_init(&client, &base_url).await?;
            }
            DbCommand::Validate => {
                db_validate(&client, &base_url).await?;
            }
        },
        Some(Commands::Build { no_cache, platform }) => {
            build_docker_image(no_cache, &platform).await?;
        }
        Some(Commands::K8s { command }) => match command {
            K8sCommand::Deploy => {
                k8s_deploy().await?;
            }
            K8sCommand::Remove => {
                k8s_remove().await?;
            }
            K8sCommand::Redeploy { no_cache, platform } => {
                k8s_redeploy(no_cache, &platform).await?;
            }
            K8sCommand::Reset { no_cache, platform } => {
                k8s_reset(no_cache, &platform).await?;
            }
        },
        Some(Commands::Iap { command }) => {
            handle_iap_command(command).await?;
        }
        None => {
            println!("Use --help for usage information or --interactive for TUI mode");
        }
    }

    Ok(())
}

fn handle_context_command(config: &mut Config, command: ContextCommand) -> Result<()> {
    match command {
        ContextCommand::Add {
            name,
            server_url,
            runtime,
            set_current,
        } => {
            // Validate runtime value
            if !["local", "distributed", "auto"].contains(&runtime.as_str()) {
                eprintln!("Invalid runtime '{}'. Use: local, distributed, or auto", runtime);
                std::process::exit(1);
            }
            
            config.contexts.insert(
                name.clone(), 
                Context::new(server_url).with_runtime(runtime)
            );
            if set_current || config.current_context.is_none() {
                config.current_context = Some(name.clone());
            }
            config.save()?;
            println!("Context '{}' added.", name);
            if config.current_context.as_ref() == Some(&name) {
                println!("Context '{}' is now the current context.", name);
            }
        }
        ContextCommand::List => {
            println!("  {:<15} {:<30} {:<12}", "NAME", "SERVER URL", "RUNTIME");
            for (name, ctx) in &config.contexts {
                let current_mark = if config.current_context.as_ref() == Some(name) {
                    "*"
                } else {
                    " "
                };
                println!("{} {:<15} {:<30} {:<12}", current_mark, name, ctx.server_url, ctx.runtime);
            }
        }
        ContextCommand::Use { name } => {
            if config.contexts.contains_key(&name) {
                config.current_context = Some(name.clone());
                config.save()?;
                let ctx = config.contexts.get(&name).unwrap();
                println!("Switched to context '{}' (runtime: {}).", name, ctx.runtime);
            } else {
                eprintln!("Context '{}' not found.", name);
                std::process::exit(1);
            }
        }
        ContextCommand::SetRuntime { runtime } => {
            // Validate runtime value
            if !["local", "distributed", "auto"].contains(&runtime.as_str()) {
                eprintln!("Invalid runtime '{}'. Use: local, distributed, or auto", runtime);
                std::process::exit(1);
            }
            
            if let Some(name) = &config.current_context {
                if let Some(ctx) = config.contexts.get_mut(name) {
                    ctx.runtime = runtime.clone();
                    config.save()?;
                    println!("Runtime for context '{}' set to '{}'.", name, runtime);
                } else {
                    eprintln!("Current context '{}' not found in contexts.", name);
                    std::process::exit(1);
                }
            } else {
                eprintln!("No current context set. Use 'noetl context use <name>' first.");
                std::process::exit(1);
            }
        }
        ContextCommand::Delete { name } => {
            if config.contexts.remove(&name).is_some() {
                if config.current_context.as_ref() == Some(&name) {
                    config.current_context = None;
                }
                config.save()?;
                println!("Context '{}' deleted.", name);
            } else {
                eprintln!("Context '{}' not found.", name);
                std::process::exit(1);
            }
        }
        ContextCommand::Current => {
            if let Some((name, ctx)) = config.get_current_context() {
                println!("Current context: {}", name);
                println!("  Server URL: {}", ctx.server_url);
                println!("  Runtime:    {}", ctx.runtime);
            } else {
                println!("No current context set.");
            }
        }
    }
    Ok(())
}

async fn register_directory(
    client: &Client,
    base_url: &str,
    resource_type: &str,
    directory: &PathBuf,
    extensions: &[&str],
) -> Result<()> {
    let files = scan_directory(directory, extensions)?;

    if files.is_empty() {
        println!("No {} files found in directory: {:?}", extensions.join(", "), directory);
        return Ok(());
    }

    println!("Found {} file(s) in {:?}", files.len(), directory);

    let mut success_count = 0;
    let mut fail_count = 0;

    for file in files {
        match register_resource(client, base_url, resource_type, &file).await {
            Ok(_) => success_count += 1,
            Err(e) => {
                eprintln!("Failed to register {:?}: {}", file, e);
                fail_count += 1;
            }
        }
    }

    println!(
        "\nRegistration complete: {} succeeded, {} failed",
        success_count, fail_count
    );
    Ok(())
}

fn scan_directory(directory: &PathBuf, extensions: &[&str]) -> Result<Vec<PathBuf>> {
    let mut files = Vec::new();

    if !directory.exists() {
        return Err(anyhow::anyhow!("Directory does not exist: {:?}", directory));
    }

    if !directory.is_dir() {
        return Err(anyhow::anyhow!("Path is not a directory: {:?}", directory));
    }

    scan_directory_recursive(directory, extensions, &mut files)?;
    Ok(files)
}

fn scan_directory_recursive(dir: &PathBuf, extensions: &[&str], files: &mut Vec<PathBuf>) -> Result<()> {
    for entry in fs::read_dir(dir).context(format!("Failed to read directory: {:?}", dir))? {
        let entry = entry?;
        let path = entry.path();

        if path.is_dir() {
            scan_directory_recursive(&path, extensions, files)?;
        } else if path.is_file() {
            if let Some(ext) = path.extension() {
                if let Some(ext_str) = ext.to_str() {
                    if extensions.contains(&ext_str) {
                        // Validate file content before adding
                        if is_valid_resource_file(&path, extensions)? {
                            files.push(path);
                        }
                    }
                }
            }
        }
    }
    Ok(())
}

fn is_valid_resource_file(file: &PathBuf, extensions: &[&str]) -> Result<bool> {
    let content = fs::read_to_string(file).context(format!("Failed to read file: {:?}", file))?;

    // Check if it's a YAML file (playbook)
    if extensions.contains(&"yaml") || extensions.contains(&"yml") {
        // Look for apiVersion and kind: Playbook
        if content.contains("apiVersion:") && content.contains("kind: Playbook") {
            return Ok(true);
        }
        return Ok(false);
    }

    // Check if it's a JSON file (credential)
    if extensions.contains(&"json") {
        // Try to parse as JSON and check for "type" field
        match serde_json::from_str::<serde_json::Value>(&content) {
            Ok(json) => {
                if json.get("type").is_some() {
                    return Ok(true);
                }
            }
            Err(_) => return Ok(false),
        }
    }

    Ok(false)
}

async fn register_resource(client: &Client, base_url: &str, resource_type: &str, file: &PathBuf) -> Result<()> {
    let content = fs::read_to_string(file).context(format!("Failed to read file: {:?}", file))?;

    let (url, request_body) = if resource_type == "Credential" {
        // For credentials, parse JSON and POST to /api/credentials
        let credential_data: serde_json::Value =
            serde_json::from_str(&content).context(format!("Failed to parse credential JSON from file: {:?}", file))?;

        (format!("{}/api/credentials", base_url), credential_data)
    } else {
        // For playbooks, base64 encode and POST to /api/catalog/register
        let content_base64 = BASE64_STANDARD.encode(&content);
        let request = RegisterRequest {
            content: content_base64,
            resource_type: resource_type.to_string(),
        };

        (
            format!("{}/api/catalog/register", base_url),
            serde_json::to_value(request)?,
        )
    };

    let response = client
        .post(&url)
        .json(&request_body)
        .send()
        .await
        .context("Failed to send register request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        println!("{} registered successfully: {}", resource_type, result);
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to register {}: {} - {}", resource_type, status, text);
        std::process::exit(1);
    }

    Ok(())
}

/// Execute playbook on distributed server-worker environment
async fn execute_playbook_distributed(
    client: &Client,
    base_url: &str,
    path: &str,
    version: Option<i64>,
    input: Option<PathBuf>,
    json_only: bool,
) -> Result<()> {
    let payload = if let Some(input_file) = input {
        let content =
            fs::read_to_string(&input_file).context(format!("Failed to read input file: {:?}", input_file))?;
        serde_json::from_str(&content).context("Failed to parse input JSON")?
    } else {
        serde_json::Value::Object(serde_json::Map::new())
    };

    // Build request with optional version
    let url = format!("{}/api/execute", base_url);
    let mut request_body = serde_json::json!({
        "path": path,
        "payload": payload
    });
    
    if let Some(v) = version {
        request_body["version"] = serde_json::json!(v);
    }

    if !json_only {
        println!("Executing playbook on distributed server...");
        println!("  Path: {}", path);
        if let Some(v) = version {
            println!("  Version: {}", v);
        }
        println!("  Server: {}", base_url);
    }

    let response = client
        .post(&url)
        .json(&request_body)
        .send()
        .await
        .context("Failed to send execute request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        if json_only {
            println!("{}", serde_json::to_string(&result)?);
        } else {
            println!("\nExecution started:");
            println!("{}", serde_json::to_string_pretty(&result)?);
            
            // Extract execution_id if available and show status command hint
            if let Some(exec_id) = result.get("execution_id") {
                println!("\nTo check status:");
                println!("  noetl execute status {}", exec_id);
            }
        }
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to execute playbook: {} - {}", status, text);
        std::process::exit(1);
    }

    Ok(())
}

async fn execute_playbook(
    client: &Client,
    base_url: &str,
    path: &str,
    input: Option<PathBuf>,
    json_only: bool,
) -> Result<()> {
    // Legacy function - delegate to new one without version
    execute_playbook_distributed(client, base_url, path, None, input, json_only).await
}

async fn get_status(client: &Client, base_url: &str, execution_id: &str, json_only: bool) -> Result<()> {
    let url = format!("{}/api/executions/{}/status", base_url, execution_id);
    let response = client.get(&url).send().await.context("Failed to send status request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        if json_only {
            println!("{}", serde_json::to_string(&result)?);
        } else {
            // Show a concise summary by default
            let completed = result.get("completed").and_then(|v| v.as_bool()).unwrap_or(false);
            let failed = result.get("failed").and_then(|v| v.as_bool()).unwrap_or(false);
            let current_step = result.get("current_step").and_then(|v| v.as_str()).unwrap_or("unknown");
            let completed_steps = result.get("completed_steps").and_then(|v| v.as_array()).map(|a| a.len()).unwrap_or(0);
            
            let status_str = if completed {
                if failed { "FAILED" } else { "COMPLETED" }
            } else {
                "RUNNING"
            };
            
            let status_color = if completed {
                if failed { "\x1b[31m" } else { "\x1b[32m" }  // red or green
            } else {
                "\x1b[33m"  // yellow
            };
            
            println!("\n{}{}\x1b[0m", status_color, "=".repeat(60));
            println!("Execution: {}", execution_id);
            println!("Status:    {}{}\x1b[0m", status_color, status_str);
            println!("Steps:     {} completed", completed_steps);
            if !completed {
                println!("Current:   {}", current_step);
            }
            
            // Show error if failed
            if failed {
                if let Some(error) = result.get("error").and_then(|v| v.as_str()) {
                    println!("\x1b[31mError:\x1b[0m     {}", error);
                }
            }
            
            // Show completed steps list
            if let Some(steps) = result.get("completed_steps").and_then(|v| v.as_array()) {
                if !steps.is_empty() {
                    println!("\nCompleted steps:");
                    for step in steps {
                        if let Some(step_name) = step.as_str() {
                            println!("  - {}", step_name);
                        }
                    }
                }
            }
            
            println!("{}{}\x1b[0m\n", status_color, "=".repeat(60));
            println!("Use --json for full execution details");
        }
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to get status: {} - {}", status, text);
    }
    Ok(())
}

async fn list_resources(client: &Client, base_url: &str, resource_type: &str, json_only: bool) -> Result<()> {
    let url = format!("{}/api/catalog/list/{}", base_url, resource_type);
    let response = client.get(&url).send().await.context("Failed to send list request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        if json_only {
            println!("{}", serde_json::to_string(&result)?);
        } else {
            println!("Catalog ({}):", resource_type);
            println!("{}", serde_json::to_string_pretty(&result)?);
        }
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to list resources: {} - {}", status, text);
    }
    Ok(())
}

async fn get_catalog_resource(client: &Client, base_url: &str, path: &str) -> Result<()> {
    let url = format!("{}/api/catalog/get/{}", base_url, path);
    let response = client
        .get(&url)
        .send()
        .await
        .context("Failed to send get catalog request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        println!("{}", serde_json::to_string_pretty(&result)?);
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to get catalog resource: {} - {}", status, text);
    }
    Ok(())
}

async fn get_credential(client: &Client, base_url: &str, name: &str, include_data: bool) -> Result<()> {
    let url = format!("{}/api/credentials/{}?include_data={}", base_url, name, include_data);
    let response = client
        .get(&url)
        .send()
        .await
        .context("Failed to send get credential request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        println!("{}", serde_json::to_string_pretty(&result)?);
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to get credential: {} - {}", status, text);
    }
    Ok(())
}

async fn execute_query(client: &Client, base_url: &str, query: &str, schema: &str, format: &str) -> Result<()> {
    let url = format!("{}/api/postgres/execute", base_url);

    let payload = serde_json::json!({
        "query": query,
        "schema": schema
    });

    let response = client
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&payload)
        .send()
        .await
        .context("Failed to send query request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;

        match format {
            "json" => {
                // Pretty print JSON
                println!("{}", serde_json::to_string_pretty(&result)?);
            }
            "table" => {
                // Extract column names from query
                let column_names = extract_column_names(query);
                // Format as table
                format_as_table(&result, &column_names)?;
            }
            _ => {
                eprintln!("Unknown format: {}. Use 'table' or 'json'", format);
                std::process::exit(1);
            }
        }
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to execute query: {} - {}", status, text);
        std::process::exit(1);
    }

    Ok(())
}

fn extract_column_names(query: &str) -> Vec<String> {
    // Simple column name extraction from SELECT query
    let query_upper = query.to_uppercase();

    // Find SELECT and FROM positions
    if let Some(select_pos) = query_upper.find("SELECT") {
        let after_select = &query[select_pos + 6..].trim_start();

        // Find FROM keyword
        let from_pos = after_select.to_uppercase().find(" FROM");
        let columns_str = if let Some(pos) = from_pos {
            &after_select[..pos]
        } else {
            after_select
        };

        // Split by comma and clean up
        let columns: Vec<String> = columns_str
            .split(',')
            .map(|s| {
                let s = s.trim();
                // Handle aliases (AS keyword)
                if let Some(as_pos) = s.to_uppercase().rfind(" AS ") {
                    s[as_pos + 4..].trim().to_string()
                } else {
                    // Get the last part after dot (for qualified names like table.column)
                    s.split('.').last().unwrap_or(s).trim().to_string()
                }
            })
            .collect();

        columns
    } else {
        Vec::new()
    }
}

fn format_as_table(result: &serde_json::Value, column_names: &[String]) -> Result<()> {
    // Check if result has the expected structure
    if let Some(result_array) = result.get("result").and_then(|r| r.as_array()) {
        if result_array.is_empty() {
            println!("(0 rows)");
            return Ok(());
        }

        // The API returns result as array of arrays: [[val1, val2], [val3, val4]]
        // We need to determine column count from first row
        let first_row = &result_array[0];
        if let Some(row_array) = first_row.as_array() {
            let col_count = row_array.len();

            // Use extracted column names if available and count matches, otherwise fall back to generic
            let columns: Vec<String> = if column_names.len() == col_count {
                column_names.to_vec()
            } else {
                (1..=col_count).map(|i| format!("column_{}", i)).collect()
            };

            // Calculate column widths
            let mut col_widths: Vec<usize> = columns.iter().map(|c| c.len()).collect();

            for row in result_array {
                if let Some(row_array) = row.as_array() {
                    for (i, val) in row_array.iter().enumerate() {
                        if i < col_widths.len() {
                            let val_str = format_value(val);
                            col_widths[i] = col_widths[i].max(val_str.len());
                        }
                    }
                }
            }

            // Print header
            print!("┌");
            for (i, width) in col_widths.iter().enumerate() {
                print!("{}", "─".repeat(width + 2));
                if i < col_widths.len() - 1 {
                    print!("┬");
                }
            }
            println!("┐");

            print!("│");
            for (i, col) in columns.iter().enumerate() {
                let width = col_widths.get(i).copied().unwrap_or(col.len());
                print!(" {:<width$} │", col, width = width);
            }
            println!();

            print!("├");
            for (i, width) in col_widths.iter().enumerate() {
                print!("{}", "─".repeat(width + 2));
                if i < col_widths.len() - 1 {
                    print!("┼");
                }
            }
            println!("┤");

            // Print rows
            for row in result_array {
                if let Some(row_array) = row.as_array() {
                    print!("│");
                    for (i, val) in row_array.iter().enumerate() {
                        if i < col_widths.len() {
                            let val_str = format_value(val);
                            let width = col_widths[i];
                            print!(" {:<width$} │", val_str, width = width);
                        }
                    }
                    println!();
                }
            }

            print!("└");
            for (i, width) in col_widths.iter().enumerate() {
                print!("{}", "─".repeat(width + 2));
                if i < col_widths.len() - 1 {
                    print!("┴");
                }
            }
            println!("┘");

            println!("({} rows)", result_array.len());
        }
    } else {
        // Fallback to pretty JSON if structure doesn't match
        println!("{}", serde_json::to_string_pretty(result)?);
    }

    Ok(())
}

fn format_value(val: &serde_json::Value) -> String {
    match val {
        serde_json::Value::Null => "NULL".to_string(),
        serde_json::Value::Bool(b) => b.to_string(),
        serde_json::Value::Number(n) => n.to_string(),
        serde_json::Value::String(s) => s.clone(),
        serde_json::Value::Array(_) | serde_json::Value::Object(_) => {
            serde_json::to_string(val).unwrap_or_else(|_| "{}".to_string())
        }
    }
}

async fn run_tui(base_url: &str) -> Result<()> {
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    let app = App::new(base_url);
    let res = run_app(&mut terminal, app).await;

    disable_raw_mode()?;
    execute!(terminal.backend_mut(), LeaveAlternateScreen, DisableMouseCapture)?;
    terminal.show_cursor()?;

    if let Err(err) = res {
        println!("{:?}", err)
    }

    Ok(())
}

struct App {
    base_url: String,
    playbooks: Vec<String>,
    state: ListState,
    client: Client,
}

impl App {
    fn new(base_url: &str) -> App {
        App {
            base_url: base_url.to_string(),
            playbooks: Vec::new(),
            state: ListState::default(),
            client: Client::new(),
        }
    }

    async fn update_playbooks(&mut self) -> Result<()> {
        let url = format!("{}/api/catalog/list/Playbook", self.base_url);
        let response = self.client.get(&url).send().await?;
        if response.status().is_success() {
            let json: serde_json::Value = response.json().await?;
            if let Some(list) = json.as_array() {
                self.playbooks = list.iter().filter_map(|v| v.as_str().map(|s| s.to_string())).collect();
            } else if let Some(obj) = json.as_object() {
                // Sometimes it might be an object where keys are paths
                self.playbooks = obj.keys().cloned().collect();
            }
        }
        Ok(())
    }

    fn next(&mut self) {
        let i = match self.state.selected() {
            Some(i) => {
                if i >= self.playbooks.len() - 1 {
                    0
                } else {
                    i + 1
                }
            }
            None => 0,
        };
        self.state.select(Some(i));
    }

    fn previous(&mut self) {
        let i = match self.state.selected() {
            Some(i) => {
                if i == 0 {
                    self.playbooks.len() - 1
                } else {
                    i - 1
                }
            }
            None => 0,
        };
        self.state.select(Some(i));
    }
}

async fn run_app<B: Backend>(terminal: &mut Terminal<B>, mut app: App) -> Result<()> {
    app.update_playbooks().await.ok();
    let tick_rate = Duration::from_millis(250);
    let mut last_tick = Instant::now();

    loop {
        terminal.draw(|f| ui(f, &mut app))?;

        let timeout = tick_rate
            .checked_sub(last_tick.elapsed())
            .unwrap_or_else(|| Duration::from_secs(0));

        if crossterm::event::poll(timeout)? {
            if let Event::Key(key) = event::read()? {
                match key.code {
                    KeyCode::Char('q') => return Ok(()),
                    KeyCode::Down | KeyCode::Char('j') => app.next(),
                    KeyCode::Up | KeyCode::Char('k') => app.previous(),
                    KeyCode::Char('r') => {
                        app.update_playbooks().await.ok();
                    }
                    _ => {}
                }
            }
        }
        if last_tick.elapsed() >= tick_rate {
            last_tick = Instant::now();
        }
    }
}

fn ui(f: &mut Frame, app: &mut App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([Constraint::Length(3), Constraint::Min(0), Constraint::Length(3)].as_ref())
        .split(f.size());

    let header = Paragraph::new("NoETL Control (noetl) - Playbooks")
        .block(Block::default().borders(Borders::ALL).title("Info"));
    f.render_widget(header, chunks[0]);

    let items: Vec<ListItem> = app.playbooks.iter().map(|i| ListItem::new(i.as_str())).collect();

    let list = List::new(items)
        .block(Block::default().borders(Borders::ALL).title("Playbooks"))
        .highlight_symbol(">> ");

    f.render_stateful_widget(list, chunks[1], &mut app.state);

    let footer = Paragraph::new("q: Quit | r: Refresh | ↑/↓: Navigate")
        .block(Block::default().borders(Borders::ALL).title("Help"));
    f.render_widget(footer, chunks[2]);
}

// ============================================================================
// Server Management
// ============================================================================

async fn start_server(init_db: bool) -> Result<()> {
    use std::net::TcpStream;
    use std::process::{Command, Stdio};

    let pid_dir = dirs::home_dir()
        .context("Could not determine home directory")?
        .join(".noetl");
    std::fs::create_dir_all(&pid_dir)?;

    let pid_file = pid_dir.join("noetl_server.pid");

    // Check if server is already running
    if pid_file.exists() {
        let pid_str = std::fs::read_to_string(&pid_file)?;
        if let Ok(pid) = pid_str.trim().parse::<i32>() {
            if process_exists(pid) {
                println!(
                    "Server already running with PID {} (PID file: {})",
                    pid,
                    pid_file.display()
                );
                println!("Use 'noetl server stop' to stop it first.");
                return Ok(());
            } else {
                println!("Found stale PID file. Removing it.");
                std::fs::remove_file(&pid_file)?;
            }
        }
    }

    // Get server configuration from environment
    let host = std::env::var("NOETL_HOST").unwrap_or_else(|_| "0.0.0.0".to_string());
    let port = std::env::var("NOETL_PORT").unwrap_or_else(|_| "8082".to_string());

    // Check port availability
    if let Ok(_stream) = TcpStream::connect(format!(
        "{}:{}",
        if host == "0.0.0.0" { "127.0.0.1" } else { &host },
        port
    )) {
        eprintln!("Error: Port {}:{} is already in use", host, port);
        return Err(anyhow::anyhow!("Port already in use"));
    }

    println!("Starting NoETL server at http://{}:{}...", host, port);

    // Spawn Python server subprocess using new entry point
    let mut cmd = Command::new("python");
    cmd.args(&["-m", "noetl.server"])
        .arg("--host")
        .arg(&host)
        .arg("--port")
        .arg(&port);

    if init_db {
        cmd.arg("--init-db");
    }

    cmd.stdout(Stdio::null()).stderr(Stdio::null());

    // Set environment variables
    if let Ok(val) = std::env::var("NOETL_ENABLE_UI") {
        cmd.env("NOETL_ENABLE_UI", val);
    }
    if let Ok(val) = std::env::var("NOETL_DEBUG") {
        cmd.env("NOETL_DEBUG", val);
    }

    let child = cmd
        .spawn()
        .context("Failed to spawn server process. Is Python and noetl package installed?")?;

    let pid = child.id();

    // Write PID file
    std::fs::write(&pid_file, pid.to_string())?;
    println!("Server started with PID {}", pid);
    println!("PID file: {}", pid_file.display());

    // Optional: Initialize database
    if init_db {
        println!("Waiting for server to be ready...");
        tokio::time::sleep(tokio::time::Duration::from_secs(3)).await;

        let client = Client::new();
        let base_url = format!("http://localhost:{}", port);

        println!("Initializing database schema...");
        let response = client.post(&format!("{}/api/db/init", base_url)).send().await;

        match response {
            Ok(resp) if resp.status().is_success() => {
                println!("Database initialized successfully.");
            }
            Ok(resp) => {
                eprintln!("Warning: Database initialization returned status {}", resp.status());
            }
            Err(e) => {
                eprintln!("Warning: Could not initialize database: {}", e);
            }
        }
    }

    Ok(())
}

async fn stop_server(force: bool) -> Result<()> {
    let pid_dir = dirs::home_dir()
        .context("Could not determine home directory")?
        .join(".noetl");
    let pid_file = pid_dir.join("noetl_server.pid");

    if !pid_file.exists() {
        println!("No running NoETL server found (no PID file at {}).", pid_file.display());
        return Ok(());
    }

    let pid_str = std::fs::read_to_string(&pid_file)?;
    let pid: i32 = pid_str.trim().parse().context("Invalid PID in file")?;

    if !process_exists(pid) {
        println!("Process {} not found. The server may have been stopped already.", pid);
        std::fs::remove_file(&pid_file)?;
        return Ok(());
    }

    if !force {
        print!("Stop NoETL server with PID {}? [y/N]: ", pid);
        std::io::Write::flush(&mut std::io::stdout())?;

        let mut input = String::new();
        std::io::stdin().read_line(&mut input)?;

        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Operation cancelled.");
            return Ok(());
        }
    }

    println!("Stopping NoETL server with PID {}...", pid);

    // Send SIGTERM
    send_signal(pid, nix::sys::signal::Signal::SIGTERM)?;

    // Wait for graceful shutdown (10 seconds)
    for _ in 0..20 {
        if !process_exists(pid) {
            std::fs::remove_file(&pid_file)?;
            println!("NoETL server stopped successfully.");
            return Ok(());
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
    }

    // Force kill if still running
    if force {
        println!("Server didn't stop gracefully. Force killing...");
        send_signal(pid, nix::sys::signal::Signal::SIGKILL)?;
    } else {
        print!("Server didn't stop gracefully. Force kill? [y/N]: ");
        std::io::Write::flush(&mut std::io::stdout())?;

        let mut input = String::new();
        std::io::stdin().read_line(&mut input)?;

        if input.trim().eq_ignore_ascii_case("y") {
            println!("Force killing NoETL server with PID {}...", pid);
            send_signal(pid, nix::sys::signal::Signal::SIGKILL)?;
        }
    }

    std::fs::remove_file(&pid_file)?;
    println!("NoETL server stopped.");

    Ok(())
}

// ============================================================================
// Worker Management
// ============================================================================

async fn start_worker(_max_workers: Option<usize>) -> Result<()> {
    use std::process::{Command, Stdio};

    let pid_dir = dirs::home_dir()
        .context("Could not determine home directory")?
        .join(".noetl");
    std::fs::create_dir_all(&pid_dir)?;

    // Determine worker name based on pool config
    let worker_name = std::env::var("NOETL_WORKER_POOL_NAME")
        .unwrap_or_else(|_| "default".to_string())
        .replace("-", "_");

    let pid_file = pid_dir.join(format!("noetl_worker_{}.pid", worker_name));

    // Check if worker is already running
    if pid_file.exists() {
        let pid_str = std::fs::read_to_string(&pid_file)?;
        if let Ok(pid) = pid_str.trim().parse::<i32>() {
            if process_exists(pid) {
                println!("Worker '{}' already running with PID {}", worker_name, pid);
                println!("Use 'noetl worker stop --name {}' to stop it first.", worker_name);
                return Ok(());
            } else {
                println!("Found stale PID file. Removing it.");
                std::fs::remove_file(&pid_file)?;
            }
        }
    }

    println!("Starting NoETL worker '{}' (v2 architecture)...", worker_name);

    // Build Python worker command - execute worker module directly
    // python -m noetl.worker starts V2 worker via __main__.py
    let mut cmd = Command::new("python");
    cmd.args(&["-m", "noetl.worker"]);

    cmd.stdout(Stdio::null()).stderr(Stdio::null());

    let child = cmd
        .spawn()
        .context("Failed to spawn worker process. Is Python and noetl package installed?")?;

    let pid = child.id();

    // Write PID file
    std::fs::write(&pid_file, pid.to_string())?;
    println!("Worker '{}' started with PID {}", worker_name, pid);
    println!("PID file: {}", pid_file.display());

    Ok(())
}

async fn stop_worker(name: Option<String>, force: bool) -> Result<()> {
    use std::io::Write;

    let pid_dir = dirs::home_dir()
        .context("Could not determine home directory")?
        .join(".noetl");

    // If no name provided, list workers and prompt
    let pid_file = if let Some(worker_name) = name {
        let normalized_name = worker_name.replace("-", "_");
        pid_dir.join(format!("noetl_worker_{}.pid", normalized_name))
    } else {
        // List all worker PID files
        let entries = std::fs::read_dir(&pid_dir)?
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.file_name().to_string_lossy().starts_with("noetl_worker_")
                    && e.file_name().to_string_lossy().ends_with(".pid")
            })
            .collect::<Vec<_>>();

        if entries.is_empty() {
            println!("No running NoETL worker services found.");
            return Ok(());
        }

        println!("Running workers:");
        for (i, entry) in entries.iter().enumerate() {
            let worker_name = entry
                .file_name()
                .to_string_lossy()
                .strip_prefix("noetl_worker_")
                .and_then(|s| s.strip_suffix(".pid"))
                .unwrap_or("unknown")
                .to_string();

            if let Ok(pid_str) = std::fs::read_to_string(entry.path()) {
                println!("  {}. {} (PID: {})", i + 1, worker_name, pid_str.trim());
            } else {
                println!("  {}. {} (PID file corrupted)", i + 1, worker_name);
            }
        }

        if entries.len() == 1 {
            entries[0].path()
        } else {
            print!("Enter the number of the worker to stop: ");
            std::io::stdout().flush()?;

            let mut input = String::new();
            std::io::stdin().read_line(&mut input)?;

            let choice: usize = input.trim().parse().context("Invalid number")?;

            if choice < 1 || choice > entries.len() {
                return Err(anyhow::anyhow!("Invalid choice"));
            }

            entries[choice - 1].path()
        }
    };

    if !pid_file.exists() {
        println!("Worker PID file not found: {}", pid_file.display());
        return Ok(());
    }

    let pid_str = std::fs::read_to_string(&pid_file)?;
    let pid: i32 = pid_str.trim().parse().context("Invalid PID in file")?;

    if !process_exists(pid) {
        println!("Process {} not found. The worker may have been stopped already.", pid);
        std::fs::remove_file(&pid_file)?;
        return Ok(());
    }

    if !force {
        print!("Stop NoETL worker with PID {}? [y/N]: ", pid);
        std::io::Write::flush(&mut std::io::stdout())?;

        let mut input = String::new();
        std::io::stdin().read_line(&mut input)?;

        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Operation cancelled.");
            return Ok(());
        }
    }

    println!("Stopping NoETL worker with PID {}...", pid);

    // Send SIGTERM
    send_signal(pid, nix::sys::signal::Signal::SIGTERM)?;

    // Wait for graceful shutdown (10 seconds)
    for _ in 0..20 {
        if !process_exists(pid) {
            std::fs::remove_file(&pid_file)?;
            println!("NoETL worker stopped successfully.");
            return Ok(());
        }
        tokio::time::sleep(tokio::time::Duration::from_millis(500)).await;
    }

    // Force kill if still running
    if force {
        println!("Worker didn't stop gracefully. Force killing...");
        send_signal(pid, nix::sys::signal::Signal::SIGKILL)?;
    } else {
        print!("Worker didn't stop gracefully. Force kill? [y/N]: ");
        std::io::Write::flush(&mut std::io::stdout())?;

        let mut input = String::new();
        std::io::stdin().read_line(&mut input)?;

        if input.trim().eq_ignore_ascii_case("y") {
            println!("Force killing NoETL worker with PID {}...", pid);
            send_signal(pid, nix::sys::signal::Signal::SIGKILL)?;
        }
    }

    std::fs::remove_file(&pid_file)?;
    println!("NoETL worker stopped.");

    Ok(())
}

// ============================================================================
// Database Management
// ============================================================================

async fn db_init(client: &Client, base_url: &str) -> Result<()> {
    println!("Initializing NoETL database schema...");

    let url = format!("{}/api/db/init", base_url);
    let response = client
        .post(&url)
        .send()
        .await
        .context("Failed to send database init request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        println!("Database initialized successfully:");
        println!("{}", serde_json::to_string_pretty(&result)?);
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to initialize database: {} - {}", status, text);
        return Err(anyhow::anyhow!("Database initialization failed"));
    }

    Ok(())
}

async fn db_validate(client: &Client, base_url: &str) -> Result<()> {
    println!("Validating NoETL database schema...");

    let url = format!("{}/api/db/validate", base_url);
    let response = client
        .get(&url)
        .send()
        .await
        .context("Failed to send database validate request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        println!("Database validation result:");
        println!("{}", serde_json::to_string_pretty(&result)?);
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to validate database: {} - {}", status, text);
        return Err(anyhow::anyhow!("Database validation failed"));
    }

    Ok(())
}

// ============================================================================
// Helper Functions for Process Management
// ============================================================================

fn process_exists(pid: i32) -> bool {
    use sysinfo::{ProcessesToUpdate, System};

    let mut system = System::new_all();
    system.refresh_processes(ProcessesToUpdate::All);

    system.process(sysinfo::Pid::from(pid as usize)).is_some()
}

fn send_signal(pid: i32, signal: nix::sys::signal::Signal) -> Result<()> {
    use nix::sys::signal::kill;
    use nix::unistd::Pid;

    kill(Pid::from_raw(pid), signal).context("Failed to send signal to process")?;

    Ok(())
}

// ============================================================================
// Build Commands
// ============================================================================

async fn build_docker_image(no_cache: bool, platform: &str) -> Result<()> {
    use chrono::Local;
    use std::io::{BufRead, BufReader};
    use std::process::Command;

    let registry = "local";
    let image_name = "noetl";
    let image_tag = Local::now().format("%Y-%m-%d-%H-%M").to_string();

    println!("Building Docker image: {}/{}:{}", registry, image_name, image_tag);
    println!("Target platform: {}", platform);

    let mut cmd = Command::new("docker");
    cmd.arg("buildx");
    cmd.arg("build");

    if no_cache {
        cmd.arg("--no-cache");
    }
    // cmd.arg("--no-cache");
    cmd.arg("--progress=plain");

    // Build for specified platform (default: linux/amd64 for Kind/K8s compatibility)
    cmd.arg("--platform").arg(platform);

    cmd.arg("-t")
        .arg(format!("{}/{}:{}", registry, image_name, image_tag))
        .arg("-f")
        .arg("docker/noetl/dev/Dockerfile")
        .arg(".")
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());

    let cr = std::env::current_dir()?;

    cmd.current_dir(cr);

    println!("cwd = {:?}", std::env::current_dir()?);

    // cmd.env("DOCKER_BUILDKIT", "0");

    println!(
        "Running: docker buildx build{} --progress=plain --platform {} -t {}/{}:{} -f docker/noetl/dev/Dockerfile .",
        if no_cache { " --no-cache" } else { "" },
        platform,
        registry,
        image_name,
        image_tag
    );

    let mut child = cmd.spawn().context("Failed to spawn docker build command")?;

    // Clone the stdout and stderr to read in separate threads
    let stdout = child.stdout.take().unwrap();
    let stderr = child.stderr.take().unwrap();

    let stdout_thread = std::thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            if let Ok(line) = line {
                println!("{}", line);
            }
        }
    });

    let stderr_thread = std::thread::spawn(move || {
        let reader = BufReader::new(stderr);
        for line in reader.lines() {
            if let Ok(line) = line {
                println!("{}", line);
            }
        }
    });

    // Wait for both threads to finish
    stdout_thread.join().unwrap();
    stderr_thread.join().unwrap();

    let status = child.wait()?;

    if !status.success() {
        return Err(anyhow::anyhow!("Docker build failed with status: {}", status));
    }

    // Save image tag to file
    std::fs::write(".noetl_last_build_tag.txt", &image_tag)?;
    println!("✓ Image built successfully: {}/{}:{}", registry, image_name, image_tag);
    println!("✓ Tag saved to .noetl_last_build_tag.txt");

    Ok(())
}

// ============================================================================
// Kubernetes Commands
// ============================================================================

async fn k8s_deploy() -> Result<()> {
    println!("Deploying NoETL to Kubernetes...");

    // Read image tag
    let image_tag = std::fs::read_to_string(".noetl_last_build_tag.txt")
        .context("Failed to read .noetl_last_build_tag.txt - have you built the image?")?;
    let image_tag = image_tag.trim();

    let registry = "local";
    let image_name = "noetl";
    let full_image = format!("{}/{}:{}", registry, image_name, image_tag);

    println!("Using image: {}", full_image);

    // Load image to kind cluster
    println!("Loading image to kind cluster...");
    run_command(&["kind", "load", "docker-image", &full_image, "--name", "noetl"])?;

    // Set kubectl context
    println!("Setting kubectl context to kind-noetl...");
    run_command(&["kubectl", "config", "use-context", "kind-noetl"])?;

    // Apply namespace
    println!("Creating namespace...");
    run_command(&["kubectl", "apply", "-f", "ci/manifests/noetl/namespace/namespace.yaml"])?;
    tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;

    // Update image in deployment files using yq
    println!("Updating deployment image references...");
    update_deployment_image("ci/manifests/noetl/server-deployment.yaml", &full_image)?;
    update_deployment_image("ci/manifests/noetl/worker-deployment.yaml", &full_image)?;

    // Apply manifests
    println!("Applying Kubernetes manifests...");
    run_command(&["kubectl", "apply", "-f", "ci/manifests/noetl/"])?;

    // Restore original image placeholders
    println!("Restoring deployment templates...");
    update_deployment_image("ci/manifests/noetl/server-deployment.yaml", "image_name:image_tag")?;
    update_deployment_image("ci/manifests/noetl/worker-deployment.yaml", "image_name:image_tag")?;

    println!("✓ NoETL deployed successfully");
    println!("  UI:  http://localhost:8082");
    println!("  API: http://localhost:8082/docs");

    Ok(())
}

async fn k8s_remove() -> Result<()> {
    println!("Removing NoETL from Kubernetes...");

    // Set kubectl context
    run_command(&["kubectl", "config", "use-context", "kind-noetl"])?;

    // Delete manifests
    run_command(&["kubectl", "delete", "-f", "ci/manifests/noetl/"])?;

    println!("✓ NoETL removed successfully");

    Ok(())
}

async fn k8s_redeploy(no_cache: bool, platform: &str) -> Result<()> {
    println!("Rebuilding and redeploying NoETL...");

    // Build image
    build_docker_image(no_cache, platform).await?;

    // Remove existing deployment
    k8s_remove().await.ok(); // Ignore errors if not deployed

    // Load image to kind
    let image_tag = std::fs::read_to_string(".noetl_last_build_tag.txt")?.trim().to_string();
    println!("Loading image to kind cluster...");
    run_command(&[
        "kind",
        "load",
        "docker-image",
        &format!("local/noetl:{}", image_tag),
        "--name",
        "noetl",
    ])?;

    // Deploy
    k8s_deploy().await?;

    println!("✓ NoETL redeployed successfully");

    Ok(())
}

async fn k8s_reset(no_cache: bool, platform: &str) -> Result<()> {
    println!("Resetting NoETL (full rebuild + schema reset + test setup)...");

    // Reset postgres schema
    println!("Resetting Postgres schema...");
    run_command(&["task", "postgres:k8s:schema-reset"])?;

    // Redeploy
    k8s_redeploy(no_cache, platform).await?;

    // Install noetl CLI with dev extras
    println!("Installing NoETL CLI with dev dependencies...");
    run_command(&["uv", "pip", "install", "-e", ".[dev]"])?;

    // Wait for deployment to be ready
    println!("Waiting for deployment to be ready...");
    tokio::time::sleep(tokio::time::Duration::from_secs(30)).await;

    // Setup test environment
    println!("Setting up test environment...");
    run_command(&["task", "test:k8s:create-tables"])?;
    run_command(&["task", "test:k8s:register-credentials"])?;

    println!("✓ NoETL reset complete");
    println!("  UI:  http://localhost:8082");
    println!("  API: http://localhost:8082/docs");

    Ok(())
}

// Helper functions for k8s commands
fn run_command(args: &[&str]) -> Result<()> {
    use std::process::Command;

    let output = Command::new(args[0])
        .args(&args[1..])
        .output()
        .context(format!("Failed to execute: {}", args.join(" ")))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(anyhow::anyhow!("Command failed: {}\n{}", args.join(" "), stderr));
    }

    print!("{}", String::from_utf8_lossy(&output.stdout));

    Ok(())
}

fn update_deployment_image(file_path: &str, image: &str) -> Result<()> {
    use std::process::Command;

    // Check which yq version is installed
    let yq_version = Command::new("yq").arg("--version").output();

    let is_mikefarah = if let Ok(output) = yq_version {
        String::from_utf8_lossy(&output.stdout).contains("mikefarah")
            || String::from_utf8_lossy(&output.stderr).contains("mikefarah")
    } else {
        false
    };

    if is_mikefarah {
        // mikefarah/yq (v4+)
        Command::new("yq")
            .arg("-i")
            .arg(format!(".spec.template.spec.containers[0].image = \"{}\"", image))
            .arg(file_path)
            .output()
            .context("Failed to update deployment with yq")?;
    } else {
        // kislyuk/yq (python version)
        let temp_file = format!("{}.tmp", file_path);
        Command::new("yq")
            .arg("-y")
            .arg(format!(".spec.template.spec.containers[0].image = \"{}\"", image))
            .arg(file_path)
            .stdout(std::fs::File::create(&temp_file)?)
            .output()
            .context("Failed to update deployment with yq")?;

        std::fs::rename(&temp_file, file_path)?;
    }

    Ok(())
}

// =============================================================================
// Infrastructure as Playbook (IaP) Command Handlers
// =============================================================================

async fn handle_iap_command(command: IapCommand) -> Result<()> {
    match command {
        IapCommand::Init {
            project,
            bucket,
            region,
            state_db,
            workspace,
            state_path,
        } => {
            iap_init(&project, bucket.as_deref(), &region, &state_db, &workspace, &state_path).await
        }
        IapCommand::Plan {
            playbook,
            variables,
            verbose,
        } => {
            iap_plan(&playbook, &variables, verbose).await
        }
        IapCommand::Apply {
            playbook,
            variables,
            auto_approve,
            verbose,
        } => {
            iap_apply(&playbook, &variables, auto_approve, verbose).await
        }
        IapCommand::State { command } => handle_iap_state_command(command).await,
        IapCommand::Sync { command } => handle_iap_sync_command(command).await,
        IapCommand::Drift { command } => handle_iap_drift_command(command).await,
        IapCommand::Workspace { command } => handle_iap_workspace_command(command).await,
    }
}

async fn handle_iap_state_command(command: IapStateCommand) -> Result<()> {
    match command {
        IapStateCommand::List { resource_type, format } => {
            iap_state_list(resource_type.as_deref(), &format).await
        }
        IapStateCommand::Show { resource } => iap_state_show(&resource).await,
        IapStateCommand::Rm { resource, force } => iap_state_rm(&resource, force).await,
        IapStateCommand::Query { sql } => iap_state_query(&sql).await,
    }
}

async fn handle_iap_sync_command(command: IapSyncCommand) -> Result<()> {
    match command {
        IapSyncCommand::Push { force } => iap_sync_push(force).await,
        IapSyncCommand::Pull { force } => iap_sync_pull(force).await,
        IapSyncCommand::Status => iap_sync_status().await,
    }
}

async fn handle_iap_drift_command(command: IapDriftCommand) -> Result<()> {
    match command {
        IapDriftCommand::Detect {
            resource_type,
            resource,
        } => {
            iap_drift_detect(resource_type.as_deref(), resource.as_deref()).await
        }
        IapDriftCommand::Report { format } => iap_drift_report(&format).await,
    }
}

async fn handle_iap_workspace_command(command: IapWorkspaceCommand) -> Result<()> {
    match command {
        IapWorkspaceCommand::List { remote } => iap_workspace_list(remote).await,
        IapWorkspaceCommand::Switch { name, pull } => iap_workspace_switch(&name, pull).await,
        IapWorkspaceCommand::Current => iap_workspace_current().await,
        IapWorkspaceCommand::Create { name, from, switch } => {
            iap_workspace_create(&name, from.as_deref(), switch).await
        }
        IapWorkspaceCommand::Delete { name, remote, force } => {
            iap_workspace_delete(&name, remote, force).await
        }
    }
}

/// Initialize IaP state database and configuration
async fn iap_init(project: &str, bucket: Option<&str>, region: &str, state_db: &str, workspace: &str, state_path_template: &str) -> Result<()> {
    use duckdb::{params, Connection};

    println!("Initializing IaP for project: {}", project);
    println!("  Region: {}", region);
    println!("  Workspace: {}", workspace);
    println!("  State DB: {}", state_db);

    // Create state directory
    let state_path = PathBuf::from(state_db);
    if let Some(parent) = state_path.parent() {
        fs::create_dir_all(parent)?;
    }

    // Open/create DuckDB database
    let conn = Connection::open(&state_path).context("Failed to create state database")?;

    // Create schema tables
    conn.execute_batch(
        r#"
        -- IaP Configuration
        CREATE TABLE IF NOT EXISTS iap_config (
            key VARCHAR PRIMARY KEY,
            value VARCHAR NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        -- Resources table - tracks all managed infrastructure
        CREATE TABLE IF NOT EXISTS resources (
            resource_id VARCHAR PRIMARY KEY,
            resource_type VARCHAR NOT NULL,
            resource_name VARCHAR NOT NULL,
            provider VARCHAR NOT NULL DEFAULT 'gcp',
            project VARCHAR,
            region VARCHAR,
            zone VARCHAR,
            status VARCHAR NOT NULL DEFAULT 'pending',
            config JSON,
            state JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_sync_at TIMESTAMP,
            drift_detected BOOLEAN DEFAULT FALSE
        );

        -- Execution history
        CREATE TABLE IF NOT EXISTS executions (
            execution_id INTEGER PRIMARY KEY,
            playbook_path VARCHAR NOT NULL,
            action VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP,
            error_message VARCHAR,
            changes JSON
        );

        -- Create sequence for execution_id
        CREATE SEQUENCE IF NOT EXISTS exec_seq START 1;

        -- Dependencies between resources
        CREATE TABLE IF NOT EXISTS dependencies (
            source_id VARCHAR NOT NULL,
            target_id VARCHAR NOT NULL,
            dependency_type VARCHAR DEFAULT 'requires',
            PRIMARY KEY (source_id, target_id)
        );

        -- Drift detection results
        CREATE TABLE IF NOT EXISTS drift_log (
            id INTEGER PRIMARY KEY,
            resource_id VARCHAR NOT NULL,
            detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            drift_type VARCHAR NOT NULL,
            expected_value JSON,
            actual_value JSON,
            resolved_at TIMESTAMP,
            resolved_by VARCHAR
        );
        "#,
    )
    .context("Failed to create schema tables")?;

    // Store configuration
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value) VALUES ('project', ?)",
        params![project],
    )?;
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value) VALUES ('region', ?)",
        params![region],
    )?;
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value) VALUES ('workspace', ?)",
        params![workspace],
    )?;
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value) VALUES ('state_path_template', ?)",
        params![state_path_template],
    )?;

    if let Some(b) = bucket {
        conn.execute(
            "INSERT OR REPLACE INTO iap_config (key, value) VALUES ('bucket', ?)",
            params![b],
        )?;
        println!("  GCS Bucket: {}", b);
        
        // Show the actual remote path that will be used
        let remote_path = state_path_template.replace("{workspace}", workspace);
        println!("  Remote Path: gs://{}/{}", b, remote_path);
    }

    // Register workspace in registry for switching
    let mut registry = load_workspace_registry()?;
    let remote_path = bucket.map(|b| {
        let path = state_path_template.replace("{workspace}", workspace);
        format!("gs://{}/{}", b, path)
    });
    let entry = WorkspaceEntry {
        name: workspace.to_string(),
        project: project.to_string(),
        region: region.to_string(),
        bucket: bucket.map(|b| b.to_string()),
        state_path_template: state_path_template.to_string(),
        remote_path,
        created_at: chrono::Utc::now().to_rfc3339(),
        last_used: Some(chrono::Utc::now().to_rfc3339()),
    };
    registry.insert(workspace.to_string(), entry);
    save_workspace_registry(&registry)?;

    println!("\nIaP initialized successfully.");
    println!("State database created at: {}", state_db);

    if bucket.is_some() {
        println!("\nTo sync state with GCS, run:");
        println!("  noetl iap sync push");
    }

    Ok(())
}

/// Plan infrastructure changes (dry-run)
async fn iap_plan(playbook: &PathBuf, variables: &[String], verbose: bool) -> Result<()> {
    println!("Planning infrastructure changes...");
    println!("  Playbook: {}", playbook.display());

    // Parse variables
    let vars = parse_variables(variables)?;
    if !vars.is_empty() {
        println!("  Variables:");
        for (k, v) in &vars {
            println!("    {} = {}", k, v);
        }
    }

    // Create playbook runner with plan mode
    let runner = playbook_runner::PlaybookRunner::new(playbook.clone())
        .with_variables(vars.clone())
        .with_verbose(verbose);

    // In plan mode, we execute but don't persist state changes
    // For now, we just show what would be executed
    println!("\nPlan output:");
    println!("{}", "-".repeat(60));

    runner.run()?;

    println!("{}", "-".repeat(60));
    println!("\nPlan complete. No changes were made.");
    println!("Run 'noetl iap apply {}' to apply these changes.", playbook.display());

    Ok(())
}

/// Apply infrastructure changes
async fn iap_apply(playbook: &PathBuf, variables: &[String], auto_approve: bool, verbose: bool) -> Result<()> {
    if !auto_approve {
        println!("This will apply infrastructure changes.");
        print!("Do you want to continue? [y/N] ");
        use std::io::{self, Write};
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;

        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Apply cancelled.");
            return Ok(());
        }
    }

    println!("Applying infrastructure changes...");
    println!("  Playbook: {}", playbook.display());

    let vars = parse_variables(variables)?;

    let runner = playbook_runner::PlaybookRunner::new(playbook.clone())
        .with_variables(vars)
        .with_verbose(verbose);

    runner.run()?;

    println!("\nApply complete.");
    Ok(())
}

// =============================================================================
// IaP Workspace Management Functions
// =============================================================================

/// Get workspace registry path
fn get_workspace_registry_path() -> PathBuf {
    PathBuf::from(".noetl/workspaces.json")
}

/// Workspace registry entry
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
struct WorkspaceEntry {
    name: String,
    project: String,
    region: String,
    bucket: Option<String>,
    state_path_template: String,
    /// Fully evaluated remote path (computed from template)
    remote_path: Option<String>,
    created_at: String,
    last_used: Option<String>,
}

/// Load workspace registry
fn load_workspace_registry() -> Result<HashMap<String, WorkspaceEntry>> {
    let registry_path = get_workspace_registry_path();
    if registry_path.exists() {
        let content = fs::read_to_string(&registry_path)?;
        Ok(serde_json::from_str(&content).unwrap_or_default())
    } else {
        Ok(HashMap::new())
    }
}

/// Save workspace registry
fn save_workspace_registry(registry: &HashMap<String, WorkspaceEntry>) -> Result<()> {
    let registry_path = get_workspace_registry_path();
    if let Some(parent) = registry_path.parent() {
        fs::create_dir_all(parent)?;
    }
    let content = serde_json::to_string_pretty(registry)?;
    fs::write(&registry_path, content)?;
    Ok(())
}

/// List workspaces
async fn iap_workspace_list(include_remote: bool) -> Result<()> {
    use duckdb::Connection;

    let registry = load_workspace_registry()?;
    
    // Get current workspace from state
    let state_path = get_state_db_path()?;
    let current_workspace = if state_path.exists() {
        let conn = Connection::open(&state_path)?;
        conn.query_row(
            "SELECT value FROM iap_config WHERE key = 'workspace'",
            [],
            |row| row.get::<_, String>(0),
        )
        .ok()
    } else {
        None
    };

    println!("Registered Workspaces:");
    println!("{:<20} {:<20} {:<15} {:<8}", "NAME", "PROJECT", "REGION", "CURRENT");
    println!("{}", "-".repeat(65));

    if registry.is_empty() && current_workspace.is_none() {
        println!("No workspaces registered. Use 'noetl iap init' to create one.");
    } else {
        for (name, entry) in &registry {
            let is_current = current_workspace.as_ref().map(|c| c == name).unwrap_or(false);
            println!(
                "{:<20} {:<20} {:<15} {}",
                name,
                &entry.project,
                &entry.region,
                if is_current { "*" } else { "" }
            );
        }

        // If current workspace isn't in registry, show it anyway
        if let Some(ref current) = current_workspace {
            if !registry.contains_key(current) {
                println!(
                    "{:<20} {:<20} {:<15} *  (not in registry)",
                    current, "-", "-"
                );
            }
        }
    }

    if include_remote {
        println!("\nChecking remote workspaces in GCS...");
        
        // Get bucket from current state or registry
        let bucket = if state_path.exists() {
            let conn = Connection::open(&state_path)?;
            conn.query_row(
                "SELECT value FROM iap_config WHERE key = 'bucket'",
                [],
                |row| row.get::<_, String>(0),
            )
            .ok()
        } else {
            None
        };

        if let Some(bucket) = bucket {
            // List workspaces folder in GCS
            let output = std::process::Command::new("gsutil")
                .args(["ls", &format!("gs://{}/workspaces/", bucket)])
                .output();

            match output {
                Ok(out) if out.status.success() => {
                    let stdout = String::from_utf8_lossy(&out.stdout);
                    let remote_workspaces: Vec<&str> = stdout
                        .lines()
                        .filter_map(|line| {
                            line.strip_prefix(&format!("gs://{}/workspaces/", bucket))
                                .and_then(|s| s.strip_suffix("/"))
                        })
                        .collect();

                    if remote_workspaces.is_empty() {
                        println!("No remote workspaces found in gs://{}/workspaces/", bucket);
                    } else {
                        println!("\nRemote Workspaces (gs://{}/workspaces/):", bucket);
                        for ws in remote_workspaces {
                            let is_local = registry.contains_key(ws) 
                                || current_workspace.as_ref().map(|c| c == ws).unwrap_or(false);
                            println!("  {} {}", ws, if is_local { "(synced)" } else { "(remote only)" });
                        }
                    }
                }
                Ok(out) => {
                    let stderr = String::from_utf8_lossy(&out.stderr);
                    if !stderr.contains("BucketNotFoundException") {
                        println!("Could not list remote workspaces: {}", stderr);
                    }
                }
                Err(e) => {
                    println!("gsutil not available: {}", e);
                }
            }
        } else {
            println!("No GCS bucket configured. Use 'noetl iap init --bucket <bucket>' first.");
        }
    }

    Ok(())
}

/// Switch to a different workspace
async fn iap_workspace_switch(name: &str, pull_after: bool) -> Result<()> {
    use duckdb::{params, Connection};

    let mut registry = load_workspace_registry()?;

    // Check if workspace exists in registry
    let entry = registry.get(name).cloned();

    if entry.is_none() {
        // Check if workspace exists remotely
        let state_path = get_state_db_path()?;
        if state_path.exists() {
            let conn = Connection::open(&state_path)?;
            let bucket: Option<String> = conn
                .query_row(
                    "SELECT value FROM iap_config WHERE key = 'bucket'",
                    [],
                    |row| row.get(0),
                )
                .ok();

            if let Some(bucket) = bucket {
                let remote_path = format!("gs://{}/workspaces/{}/state.duckdb", bucket, name);
                let check = std::process::Command::new("gsutil")
                    .args(["stat", &remote_path])
                    .output();

                if let Ok(out) = check {
                    if out.status.success() {
                        println!("Workspace '{}' found in remote storage.", name);
                        println!("Creating local entry and pulling state...");
                        
                        // Get project and region from current config
                        let project: String = conn
                            .query_row(
                                "SELECT value FROM iap_config WHERE key = 'project'",
                                [],
                                |row| row.get(0),
                            )
                            .unwrap_or_else(|_| "unknown".to_string());
                        let region: String = conn
                            .query_row(
                                "SELECT value FROM iap_config WHERE key = 'region'",
                                [],
                                |row| row.get(0),
                            )
                            .unwrap_or_else(|_| "us-central1".to_string());

                        // Create registry entry
                        let remote_path = format!("gs://{}/workspaces/{}/state.duckdb", bucket, name);
                        let new_entry = WorkspaceEntry {
                            name: name.to_string(),
                            project: project.clone(),
                            region: region.clone(),
                            bucket: Some(bucket.clone()),
                            state_path_template: "workspaces/{workspace}/state.duckdb".to_string(),
                            remote_path: Some(remote_path),
                            created_at: chrono::Utc::now().to_rfc3339(),
                            last_used: None,
                        };
                        registry.insert(name.to_string(), new_entry);
                        save_workspace_registry(&registry)?;

                        // Update current workspace in state
                        conn.execute(
                            "INSERT OR REPLACE INTO iap_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                            params!["workspace", name],
                        )?;

                        // Pull state
                        iap_sync_pull(true).await?;
                        
                        println!("\nSwitched to workspace '{}'.", name);
                        return Ok(());
                    }
                }
            }
        }

        return Err(anyhow::anyhow!(
            "Workspace '{}' not found in registry or remote storage.\n\
             Use 'noetl iap workspace create {}' to create a new workspace, or\n\
             Use 'noetl iap workspace list --remote' to see available remote workspaces.",
            name, name
        ));
    }

    // Workspace exists in registry
    let entry = entry.unwrap();
    let state_path = get_state_db_path()?;

    // Update workspace in state database
    let conn = Connection::open(&state_path)?;
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        params!["workspace", name],
    )?;
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        params!["project", &entry.project],
    )?;
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        params!["region", &entry.region],
    )?;
    if let Some(ref bucket) = entry.bucket {
        conn.execute(
            "INSERT OR REPLACE INTO iap_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
            params!["bucket", bucket],
        )?;
    }
    conn.execute(
        "INSERT OR REPLACE INTO iap_config (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        params!["state_path_template", &entry.state_path_template],
    )?;

    // Update last_used in registry
    if let Some(entry) = registry.get_mut(name) {
        entry.last_used = Some(chrono::Utc::now().to_rfc3339());
    }
    save_workspace_registry(&registry)?;

    println!("Switched to workspace '{}'.", name);
    println!("  Project: {}", entry.project);
    println!("  Region: {}", entry.region);
    if let Some(bucket) = &entry.bucket {
        println!("  Bucket: {}", bucket);
    }

    if pull_after {
        println!("\nPulling state from remote...");
        iap_sync_pull(true).await?;
    }

    Ok(())
}

/// Show current workspace info
async fn iap_workspace_current() -> Result<()> {
    use duckdb::Connection;

    let state_path = get_state_db_path()?;
    if !state_path.exists() {
        return Err(anyhow::anyhow!(
            "No state database found. Run 'noetl iap init' first."
        ));
    }

    let conn = Connection::open(&state_path)?;

    let workspace: String = conn
        .query_row(
            "SELECT value FROM iap_config WHERE key = 'workspace'",
            [],
            |row| row.get(0),
        )
        .unwrap_or_else(|_| "default".to_string());

    let project: String = conn
        .query_row(
            "SELECT value FROM iap_config WHERE key = 'project'",
            [],
            |row| row.get(0),
        )
        .unwrap_or_else(|_| "-".to_string());

    let region: String = conn
        .query_row(
            "SELECT value FROM iap_config WHERE key = 'region'",
            [],
            |row| row.get(0),
        )
        .unwrap_or_else(|_| "-".to_string());

    let bucket: String = conn
        .query_row(
            "SELECT value FROM iap_config WHERE key = 'bucket'",
            [],
            |row| row.get(0),
        )
        .unwrap_or_else(|_| "(not configured)".to_string());

    let state_path_template: String = conn
        .query_row(
            "SELECT value FROM iap_config WHERE key = 'state_path_template'",
            [],
            |row| row.get(0),
        )
        .unwrap_or_else(|_| "workspaces/{workspace}/state.duckdb".to_string());

    // Get resource count
    let resource_count: i64 = conn
        .query_row("SELECT COUNT(*) FROM resources", [], |row| row.get(0))
        .unwrap_or(0);

    println!("Current Workspace: {}", workspace);
    println!();
    println!("Configuration:");
    println!("  Project:     {}", project);
    println!("  Region:      {}", region);
    println!("  GCS Bucket:  {}", bucket);
    println!("  State Path:  {}", state_path_template.replace("{workspace}", &workspace));
    println!();
    println!("State:");
    println!("  Local DB:    {}", state_path.display());
    println!("  Resources:   {}", resource_count);

    Ok(())
}

/// Create a new workspace
async fn iap_workspace_create(name: &str, from: Option<&str>, switch_to: bool) -> Result<()> {
    use duckdb::Connection;

    let mut registry = load_workspace_registry()?;

    // Check if workspace already exists
    if registry.contains_key(name) {
        return Err(anyhow::anyhow!(
            "Workspace '{}' already exists. Use 'noetl iap workspace switch {}' to switch to it.",
            name, name
        ));
    }

    // Get configuration from current state or source workspace
    let (project, region, bucket, state_path_template) = if let Some(source) = from {
        // Clone from existing workspace
        if let Some(entry) = registry.get(source) {
            (
                entry.project.clone(),
                entry.region.clone(),
                entry.bucket.clone(),
                entry.state_path_template.clone(),
            )
        } else {
            return Err(anyhow::anyhow!(
                "Source workspace '{}' not found in registry.",
                source
            ));
        }
    } else {
        // Get from current state
        let state_path = get_state_db_path()?;
        if !state_path.exists() {
            return Err(anyhow::anyhow!(
                "No state database found. Run 'noetl iap init' first, or use --from to clone from existing workspace."
            ));
        }

        let conn = Connection::open(&state_path)?;
        let project: String = conn
            .query_row(
                "SELECT value FROM iap_config WHERE key = 'project'",
                [],
                |row| row.get(0),
            )
            .context("Project not configured. Run 'noetl iap init' first.")?;
        let region: String = conn
            .query_row(
                "SELECT value FROM iap_config WHERE key = 'region'",
                [],
                |row| row.get(0),
            )
            .unwrap_or_else(|_| "us-central1".to_string());
        let bucket: Option<String> = conn
            .query_row(
                "SELECT value FROM iap_config WHERE key = 'bucket'",
                [],
                |row| row.get(0),
            )
            .ok();
        let state_path_template: String = conn
            .query_row(
                "SELECT value FROM iap_config WHERE key = 'state_path_template'",
                [],
                |row| row.get(0),
            )
            .unwrap_or_else(|_| "workspaces/{workspace}/state.duckdb".to_string());

        (project, region, bucket, state_path_template)
    };

    // Create registry entry
    let remote_path = bucket.as_ref().map(|b| {
        let path = state_path_template.replace("{workspace}", name);
        format!("gs://{}/{}", b, path)
    });
    let entry = WorkspaceEntry {
        name: name.to_string(),
        project: project.clone(),
        region: region.clone(),
        bucket: bucket.clone(),
        state_path_template: state_path_template.clone(),
        remote_path,
        created_at: chrono::Utc::now().to_rfc3339(),
        last_used: None,
    };

    registry.insert(name.to_string(), entry);
    save_workspace_registry(&registry)?;

    println!("Created workspace '{}'.", name);
    println!("  Project: {}", project);
    println!("  Region: {}", region);
    if let Some(ref bucket) = bucket {
        let remote_path = state_path_template.replace("{workspace}", name);
        println!("  Remote: gs://{}/{}", bucket, remote_path);
    }

    if switch_to {
        println!();
        iap_workspace_switch(name, false).await?;
    } else {
        println!("\nTo switch to this workspace, run:");
        println!("  noetl iap workspace switch {}", name);
    }

    Ok(())
}

/// Delete a workspace from registry
async fn iap_workspace_delete(name: &str, delete_remote: bool, force: bool) -> Result<()> {
    use duckdb::Connection;
    use std::io::{self, Write};

    let mut registry = load_workspace_registry()?;

    // Check if it's the current workspace
    let state_path = get_state_db_path()?;
    let current_workspace = if state_path.exists() {
        let conn = Connection::open(&state_path)?;
        conn.query_row(
            "SELECT value FROM iap_config WHERE key = 'workspace'",
            [],
            |row| row.get::<_, String>(0),
        )
        .ok()
    } else {
        None
    };

    if current_workspace.as_ref().map(|c| c == name).unwrap_or(false) {
        return Err(anyhow::anyhow!(
            "Cannot delete current workspace '{}'. Switch to a different workspace first.",
            name
        ));
    }

    if !registry.contains_key(name) {
        return Err(anyhow::anyhow!(
            "Workspace '{}' not found in registry.",
            name
        ));
    }

    if !force {
        print!("Delete workspace '{}'? ", name);
        if delete_remote {
            print!("(including remote state) ");
        }
        print!("[y/N] ");
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;
        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Aborted.");
            return Ok(());
        }
    }

    // Delete remote state if requested
    if delete_remote {
        if let Some(entry) = registry.get(name) {
            if let Some(ref bucket) = entry.bucket {
                let remote_path = entry.state_path_template.replace("{workspace}", name);
                let gcs_path = format!("gs://{}/{}", bucket, remote_path);
                
                println!("Deleting remote state: {}", gcs_path);
                let output = std::process::Command::new("gsutil")
                    .args(["rm", &gcs_path])
                    .output();

                match output {
                    Ok(out) if out.status.success() => {
                        println!("Remote state deleted.");
                    }
                    Ok(out) => {
                        let stderr = String::from_utf8_lossy(&out.stderr);
                        if !stderr.contains("No URLs matched") {
                            println!("Warning: Could not delete remote state: {}", stderr);
                        }
                    }
                    Err(e) => {
                        println!("Warning: Could not delete remote state: {}", e);
                    }
                }
            }
        }
    }

    // Remove from registry
    registry.remove(name);
    save_workspace_registry(&registry)?;

    println!("Workspace '{}' removed from registry.", name);

    Ok(())
}

/// List resources in state
async fn iap_state_list(resource_type: Option<&str>, format: &str) -> Result<()> {
    use duckdb::Connection;

    let state_path = get_state_db_path()?;
    let conn = Connection::open(&state_path).context("Failed to open state database")?;

    let query = if let Some(rt) = resource_type {
        format!(
            "SELECT resource_id, resource_type, resource_name, status, updated_at 
             FROM resources WHERE resource_type = '{}' ORDER BY resource_type, resource_name",
            rt
        )
    } else {
        "SELECT resource_id, resource_type, resource_name, status, updated_at 
         FROM resources ORDER BY resource_type, resource_name"
            .to_string()
    };

    let mut stmt = conn.prepare(&query)?;
    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, String>(3)?,
            row.get::<_, String>(4)?,
        ))
    })?;

    let results: Vec<_> = rows.filter_map(|r| r.ok()).collect();

    if results.is_empty() {
        println!("No resources found in state.");
        return Ok(());
    }

    match format {
        "json" => {
            let json_results: Vec<serde_json::Value> = results
                .iter()
                .map(|(id, rtype, name, status, updated)| {
                    serde_json::json!({
                        "resource_id": id,
                        "resource_type": rtype,
                        "resource_name": name,
                        "status": status,
                        "updated_at": updated
                    })
                })
                .collect();
            println!("{}", serde_json::to_string_pretty(&json_results)?);
        }
        _ => {
            println!(
                "{:<40} {:<15} {:<25} {:<10} {}",
                "RESOURCE ID", "TYPE", "NAME", "STATUS", "UPDATED"
            );
            println!("{}", "-".repeat(100));
            for (id, rtype, name, status, updated) in results {
                println!("{:<40} {:<15} {:<25} {:<10} {}", id, rtype, name, status, updated);
            }
        }
    }

    Ok(())
}

/// Show details for a specific resource
async fn iap_state_show(resource: &str) -> Result<()> {
    use duckdb::Connection;

    let state_path = get_state_db_path()?;
    let conn = Connection::open(&state_path)?;

    let mut stmt = conn.prepare(
        "SELECT resource_id, resource_type, resource_name, provider, project, region, zone,
                status, config, state, created_at, updated_at, last_sync_at, drift_detected
         FROM resources WHERE resource_id = ? OR resource_name = ?",
    )?;

    let result = stmt.query_row([resource, resource], |row| {
        Ok(serde_json::json!({
            "resource_id": row.get::<_, String>(0)?,
            "resource_type": row.get::<_, String>(1)?,
            "resource_name": row.get::<_, String>(2)?,
            "provider": row.get::<_, String>(3)?,
            "project": row.get::<_, Option<String>>(4)?,
            "region": row.get::<_, Option<String>>(5)?,
            "zone": row.get::<_, Option<String>>(6)?,
            "status": row.get::<_, String>(7)?,
            "config": row.get::<_, Option<String>>(8)?,
            "state": row.get::<_, Option<String>>(9)?,
            "created_at": row.get::<_, String>(10)?,
            "updated_at": row.get::<_, String>(11)?,
            "last_sync_at": row.get::<_, Option<String>>(12)?,
            "drift_detected": row.get::<_, bool>(13)?
        }))
    });

    match result {
        Ok(json) => {
            println!("{}", serde_json::to_string_pretty(&json)?);
        }
        Err(_) => {
            println!("Resource not found: {}", resource);
        }
    }

    Ok(())
}

/// Remove a resource from state
async fn iap_state_rm(resource: &str, force: bool) -> Result<()> {
    use duckdb::Connection;

    if !force {
        print!("Remove '{}' from state? This does not destroy the actual resource. [y/N] ", resource);
        use std::io::{self, Write};
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;

        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Cancelled.");
            return Ok(());
        }
    }

    let state_path = get_state_db_path()?;
    let conn = Connection::open(&state_path)?;

    let deleted = conn.execute(
        "DELETE FROM resources WHERE resource_id = ? OR resource_name = ?",
        [resource, resource],
    )?;

    if deleted > 0 {
        println!("Resource '{}' removed from state.", resource);
    } else {
        println!("Resource '{}' not found in state.", resource);
    }

    Ok(())
}

/// Execute raw SQL query against state database
async fn iap_state_query(sql: &str) -> Result<()> {
    use std::process::Command;

    let state_path = get_state_db_path()?;
    
    // Use duckdb CLI for arbitrary queries (the Rust crate has bugs with query_arrow)
    let output = Command::new("duckdb")
        .arg(&state_path)
        .arg("-c")
        .arg(sql)
        .output();
    
    match output {
        Ok(out) => {
            if out.status.success() {
                print!("{}", String::from_utf8_lossy(&out.stdout));
                if !out.stderr.is_empty() {
                    eprint!("{}", String::from_utf8_lossy(&out.stderr));
                }
                Ok(())
            } else {
                let stderr = String::from_utf8_lossy(&out.stderr);
                Err(anyhow::anyhow!("DuckDB query failed: {}", stderr))
            }
        }
        Err(e) => {
            Err(anyhow::anyhow!(
                "DuckDB CLI not found. Install with: brew install duckdb\nError: {}",
                e
            ))
        }
    }
}

/// Push local state to GCS
async fn iap_sync_push(force: bool) -> Result<()> {
    use duckdb::Connection;

    let state_path = get_state_db_path()?;
    let conn = Connection::open(&state_path)?;

    // Get configuration from state database
    let bucket: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'bucket'", [], |row| row.get(0))
        .context("GCS bucket not configured. Run 'noetl iap init --bucket <bucket>' first.")?;

    let workspace: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'workspace'", [], |row| row.get(0))
        .unwrap_or_else(|_| "default".to_string());

    let state_path_template: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'state_path_template'", [], |row| row.get(0))
        .unwrap_or_else(|_| "workspaces/{workspace}/state.duckdb".to_string());

    // Build remote path from template
    let remote_path = state_path_template.replace("{workspace}", &workspace);
    let gcs_path = format!("gs://{}/{}", bucket, remote_path);

    if !force {
        print!("Push state to {}? [y/N] ", gcs_path);
        use std::io::{self, Write};
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;

        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Cancelled.");
            return Ok(());
        }
    }

    println!("Pushing state to {}...", gcs_path);

    // Close connection before copying
    drop(conn);

    // Use gsutil to copy
    let output = std::process::Command::new("gsutil")
        .args(["cp", state_path.to_str().unwrap(), &gcs_path])
        .output()
        .context("Failed to push state to GCS (gsutil not available?)")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("Failed to push state: {}", stderr);
    }

    println!("State pushed successfully.");
    Ok(())
}

/// Pull state from GCS to local
async fn iap_sync_pull(force: bool) -> Result<()> {
    use duckdb::Connection;

    let state_path = get_state_db_path()?;

    // Try to get config from existing state, or require it
    if !state_path.exists() {
        return Err(anyhow::anyhow!(
            "No local state found. Run 'noetl iap init' first to configure project and bucket."
        ));
    }

    let conn = Connection::open(&state_path)?;
    
    let bucket: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'bucket'", [], |row| row.get(0))
        .context("GCS bucket not configured")?;

    let workspace: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'workspace'", [], |row| row.get(0))
        .unwrap_or_else(|_| "default".to_string());

    let state_path_template: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'state_path_template'", [], |row| row.get(0))
        .unwrap_or_else(|_| "workspaces/{workspace}/state.duckdb".to_string());

    // Build remote path from template
    let remote_path = state_path_template.replace("{workspace}", &workspace);
    let gcs_path = format!("gs://{}/{}", bucket, remote_path);

    // Close connection before pulling
    drop(conn);

    if !force {
        print!(
            "Pull state from {}? This will overwrite local state. [y/N] ",
            gcs_path
        );
        use std::io::{self, Write};
        io::stdout().flush()?;

        let mut input = String::new();
        io::stdin().read_line(&mut input)?;

        if !input.trim().eq_ignore_ascii_case("y") {
            println!("Cancelled.");
            return Ok(());
        }
    }

    println!("Pulling state from {}...", gcs_path);

    let output = std::process::Command::new("gsutil")
        .args(["cp", &gcs_path, state_path.to_str().unwrap()])
        .output()
        .context("Failed to pull state from GCS (gsutil not available?)")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!("Failed to pull state: {}", stderr);
    }

    println!("State pulled successfully.");
    Ok(())
}

/// Show sync status
async fn iap_sync_status() -> Result<()> {
    use duckdb::Connection;

    let state_path = get_state_db_path()?;

    if !state_path.exists() {
        println!("No local state found.");
        return Ok(());
    }

    let conn = Connection::open(&state_path)?;

    let bucket: Result<String, _> =
        conn.query_row("SELECT value FROM iap_config WHERE key = 'bucket'", [], |row| row.get(0));

    let project: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'project'", [], |row| row.get(0))
        .unwrap_or_else(|_| "unknown".to_string());

    let workspace: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'workspace'", [], |row| row.get(0))
        .unwrap_or_else(|_| "default".to_string());

    let state_path_template: String = conn
        .query_row("SELECT value FROM iap_config WHERE key = 'state_path_template'", [], |row| row.get(0))
        .unwrap_or_else(|_| "workspaces/{workspace}/state.duckdb".to_string());

    println!("Local state: {}", state_path.display());
    println!("Project: {}", project);
    println!("Workspace: {}", workspace);

    match bucket {
        Ok(b) => {
            let remote_path = state_path_template.replace("{workspace}", &workspace);
            let gcs_path = format!("gs://{}/{}", b, remote_path);
            println!("Remote: {}", gcs_path);

            // Check if remote exists
            let output = std::process::Command::new("gsutil")
                .args(["ls", &gcs_path])
                .output();

            match output {
                Ok(o) if o.status.success() => {
                    println!("Remote state: exists");
                }
                _ => {
                    println!("Remote state: not found");
                }
            }
        }
        Err(_) => {
            println!("Remote: not configured");
        }
    }

    // Count local resources
    let count: i64 = conn
        .query_row("SELECT COUNT(*) FROM resources", [], |row| row.get(0))
        .unwrap_or(0);

    println!("Local resources: {}", count);

    Ok(())
}

/// Detect drift between state and actual resources
async fn iap_drift_detect(_resource_type: Option<&str>, _resource: Option<&str>) -> Result<()> {
    println!("Drift detection requires cloud API access.");
    println!("This feature is not yet implemented.");
    println!("\nTo detect drift, the system would:");
    println!("1. Read resources from local state");
    println!("2. Query GCP APIs for current resource state");
    println!("3. Compare and report differences");
    Ok(())
}

/// Show drift report
async fn iap_drift_report(format: &str) -> Result<()> {
    use duckdb::Connection;

    let state_path = get_state_db_path()?;
    let conn = Connection::open(&state_path)?;

    let mut stmt = conn.prepare(
        "SELECT resource_id, detected_at, drift_type, expected_value, actual_value
         FROM drift_log WHERE resolved_at IS NULL ORDER BY detected_at DESC",
    )?;

    let rows = stmt.query_map([], |row| {
        Ok((
            row.get::<_, String>(0)?,
            row.get::<_, String>(1)?,
            row.get::<_, String>(2)?,
            row.get::<_, Option<String>>(3)?,
            row.get::<_, Option<String>>(4)?,
        ))
    })?;

    let results: Vec<_> = rows.filter_map(|r| r.ok()).collect();

    if results.is_empty() {
        println!("No drift detected.");
        return Ok(());
    }

    match format {
        "json" => {
            let json_results: Vec<serde_json::Value> = results
                .iter()
                .map(|(id, detected, dtype, expected, actual)| {
                    serde_json::json!({
                        "resource_id": id,
                        "detected_at": detected,
                        "drift_type": dtype,
                        "expected": expected,
                        "actual": actual
                    })
                })
                .collect();
            println!("{}", serde_json::to_string_pretty(&json_results)?);
        }
        _ => {
            println!(
                "{:<40} {:<20} {:<15}",
                "RESOURCE", "DETECTED", "DRIFT TYPE"
            );
            println!("{}", "-".repeat(80));
            for (id, detected, dtype, _, _) in results {
                println!("{:<40} {:<20} {:<15}", id, detected, dtype);
            }
        }
    }

    Ok(())
}

/// Parse key=value variables
fn parse_variables(variables: &[String]) -> Result<std::collections::HashMap<String, String>> {
    let mut vars = std::collections::HashMap::new();
    for var in variables {
        let parts: Vec<&str> = var.splitn(2, '=').collect();
        if parts.len() != 2 {
            return Err(anyhow::anyhow!("Invalid variable format: {}. Expected key=value", var));
        }
        vars.insert(parts[0].to_string(), parts[1].to_string());
    }
    Ok(vars)
}

/// Get the default state database path
fn get_state_db_path() -> Result<PathBuf> {
    let path = PathBuf::from(".noetl/state.duckdb");
    Ok(path)
}
