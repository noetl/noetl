mod config;

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
    /// Context management
    Context {
        #[command(subcommand)]
        command: ContextCommand,
    },
    /// Execute a playbook (legacy command, use 'execute playbook' instead)
    /// Examples:
    ///     noetlctl exec my-playbook
    ///     noetlctl exec workflows/data-pipeline --input params.json
    ///     noetlctl --host=localhost --port=8082 exec etl-job --input /path/to/input.json --json
    #[command(verbatim_doc_comment)]
    Exec {
        /// Playbook path/name as registered in catalog
        playbook_path: String,

        /// Path to JSON file with parameters
        #[arg(short, long)]
        input: Option<PathBuf>,

        /// Emit only the JSON response
        #[arg(short, long)]
        json: bool,
    },
    /// Register resources
    Register {
        #[command(subcommand)]
        resource: RegisterResource,
    },
    /// Fetch execution status (legacy command, use 'execute status' instead)
    /// Examples:
    ///     noetlctl status 12345
    ///     noetlctl --host=localhost --port=8082 status 12345 --json
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
    ///     noetlctl list Playbook
    ///     noetlctl list Credential --json
    ///     noetlctl --host=localhost --port=8082 list Playbook
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
    /// Execution management
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
}

#[derive(Subcommand)]
enum CatalogCommand {
    /// Register a resource (auto-detects type)
    /// Example for playbooks:
    ///     noetlctl catalog register tests/fixtures/playbooks/hello_world/hello_world.yaml
    ///     noetlctl --host=localhost --port=8082 catalog register tests/fixtures/playbooks/hello_world/hello_world.yaml
    /// Example for credential:
    ///     noetlctl --host=localhost --port=8082 catalog register tests/fixtures/credentials/google_oauth.json
    #[command(verbatim_doc_comment)]
    Register {
        /// Path to the resource file
        file: PathBuf,
    },
    /// Get resource details from catalog
    /// Examples:
    ///     noetlctl catalog get my-playbook
    ///     noetlctl --host=localhost --port=8082 catalog get workflows/data-pipeline
    ///     noetlctl catalog get my-credential
    #[command(verbatim_doc_comment)]
    Get {
        /// Resource path/name
        path: String,
    },
    /// List resources in catalog by type
    /// Examples:
    ///     noetlctl catalog list Playbook
    ///     noetlctl catalog list Credential
    ///     noetlctl --host=localhost --port=8082 catalog list Playbook --json
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
    ///     noetlctl execute playbook my-playbook
    ///     noetlctl execute playbook workflows/etl-pipeline --input params.json
    ///     noetlctl --host=localhost --port=8082 execute playbook data-sync --input /path/to/input.json --json
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
    ///     noetlctl execute status 12345
    ///     noetlctl --host=localhost --port=8082 execute status 12345 --json
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
    ///     noetlctl get credential my-db-creds
    ///     noetlctl get credential google_oauth --include_data=false
    ///     noetlctl --host=localhost --port=8082 get credential aws-credentials
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
    ///     noetlctl register credential --file credentials/postgres.json
    ///     noetlctl register credential --directory tests/fixtures/credentials
    ///     noetlctl --host=localhost --port=8082 register credential -f tests/fixtures/credentials/google_oauth.json
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
    ///     noetlctl register playbook --file playbooks/my-workflow.yaml
    ///     noetlctl register playbook --directory tests/fixtures/playbooks
    ///     noetlctl --host=localhost --port=8082 register playbook -f tests/fixtures/playbooks/hello_world/hello_world.yaml
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
enum ContextCommand {
    /// Add a new context for connecting to NoETL servers
    /// Examples:
    ///     noetlctl context add local --server-url=http://localhost:8082
    ///     noetlctl context add prod --server-url=https://noetl.example.com --set-current
    ///     noetlctl context add staging --server-url=http://staging:8082
    #[command(verbatim_doc_comment)]
    Add {
        /// Context name
        name: String,
        /// Server URL (e.g., http://localhost:8082)
        #[arg(long)]
        server_url: String,
        /// Set as current context
        #[arg(long)]
        set_current: bool,
    },
    /// List all configured contexts
    /// Example:
    ///     noetlctl context list
    #[command(verbatim_doc_comment)]
    List,
    /// Switch to a different context
    /// Examples:
    ///     noetlctl context use local
    ///     noetlctl context use prod
    #[command(verbatim_doc_comment)]
    Use {
        /// Context name to switch to
        name: String,
    },
    /// Delete a context
    /// Examples:
    ///     noetlctl context delete old-env
    ///     noetlctl context delete staging
    #[command(verbatim_doc_comment)]
    Delete {
        /// Context name to delete
        name: String,
    },
    /// Show current active context
    /// Example:
    ///     noetlctl context current
    #[command(verbatim_doc_comment)]
    Current,
}

#[derive(Serialize)]
struct RegisterRequest {
    content: String,
    resource_type: String,
}

#[derive(Serialize)]
struct ExecuteRequest {
    path: String,
    payload: serde_json::Value,
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
        Some(Commands::Context { command }) => {
            handle_context_command(&mut config, command)?;
        }
        Some(Commands::Exec {
            playbook_path,
            input,
            json,
        }) => {
            execute_playbook(&client, &base_url, &playbook_path, input, json).await?;
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
            set_current,
        } => {
            config.contexts.insert(name.clone(), Context { server_url });
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
            println!("  {:<20} {:<30}", "NAME", "SERVER URL");
            for (name, ctx) in &config.contexts {
                let current_mark = if config.current_context.as_ref() == Some(name) {
                    "*"
                } else {
                    " "
                };
                println!("{} {:<20} {:<30}", current_mark, name, ctx.server_url);
            }
        }
        ContextCommand::Use { name } => {
            if config.contexts.contains_key(&name) {
                config.current_context = Some(name.clone());
                config.save()?;
                println!("Switched to context '{}'.", name);
            } else {
                eprintln!("Context '{}' not found.", name);
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
                println!("Current context: {} ({})", name, ctx.server_url);
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
    
    println!("\nRegistration complete: {} succeeded, {} failed", success_count, fail_count);
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
    let content = fs::read_to_string(file)
        .context(format!("Failed to read file: {:?}", file))?;
    
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
        let credential_data: serde_json::Value = serde_json::from_str(&content)
            .context(format!("Failed to parse credential JSON from file: {:?}", file))?;
        
        (
            format!("{}/api/credentials", base_url),
            credential_data
        )
    } else {
        // For playbooks, base64 encode and POST to /api/catalog/register
        let content_base64 = BASE64_STANDARD.encode(&content);
        let request = RegisterRequest {
            content: content_base64,
            resource_type: resource_type.to_string(),
        };
        
        (
            format!("{}/api/catalog/register", base_url),
            serde_json::to_value(request)?
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

async fn execute_playbook(
    client: &Client,
    base_url: &str,
    path: &str,
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

    let url = format!("{}/api/execute", base_url);
    let request = ExecuteRequest {
        path: path.to_string(),
        payload,
    };

    let response = client
        .post(&url)
        .json(&request)
        .send()
        .await
        .context("Failed to send execute request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        if json_only {
            println!("{}", serde_json::to_string(&result)?);
        } else {
            println!("Execution started: {}", serde_json::to_string_pretty(&result)?);
        }
    } else {
        let status = response.status();
        let text = response.text().await?;
        eprintln!("Failed to execute playbook: {} - {}", status, text);
        std::process::exit(1);
    }

    Ok(())
}

async fn get_status(client: &Client, base_url: &str, execution_id: &str, json_only: bool) -> Result<()> {
    let url = format!("{}/api/execute/status/{}", base_url, execution_id);
    let response = client.get(&url).send().await.context("Failed to send status request")?;

    if response.status().is_success() {
        let result: serde_json::Value = response.json().await?;
        if json_only {
            println!("{}", serde_json::to_string(&result)?);
        } else {
            println!("Status: {}", serde_json::to_string_pretty(&result)?);
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
                print!(" {:width$} │", col, width = col_widths[i]);
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
                            print!(" {:width$} │", val_str, width = col_widths[i]);
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

    let header = Paragraph::new("NoETL Control (noetlctl) - Playbooks")
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
