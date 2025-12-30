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
#[command(name = "noetlctl")]
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
    /// Register a credential from JSON file
    /// Examples:
    ///     noetlctl register credential --file credentials/postgres.json
    ///     noetlctl --host=localhost --port=8082 register credential -f tests/fixtures/credentials/google_oauth.json
    #[command(verbatim_doc_comment)]
    Credential {
        /// Path to credential file
        #[arg(short, long)]
        file: PathBuf,
    },
    /// Register a playbook from YAML file
    /// Examples:
    ///     noetlctl register playbook --file playbooks/my-workflow.yaml
    ///     noetlctl --host=localhost --port=8082 register playbook -f tests/fixtures/playbooks/hello_world/hello_world.yaml
    #[command(verbatim_doc_comment)]
    Playbook {
        /// Path to playbook file
        #[arg(short, long)]
        file: PathBuf,
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
            RegisterResource::Credential { file } => {
                register_resource(&client, &base_url, "Credential", &file).await?;
            }
            RegisterResource::Playbook { file } => {
                register_resource(&client, &base_url, "Playbook", &file).await?;
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

async fn register_resource(client: &Client, base_url: &str, resource_type: &str, file: &PathBuf) -> Result<()> {
    let content = fs::read_to_string(file).context(format!("Failed to read file: {:?}", file))?;
    let content_base64 = BASE64_STANDARD.encode(content);

    let url = format!("{}/api/catalog/register", base_url);
    let request = RegisterRequest {
        content: content_base64,
        resource_type: resource_type.to_string(),
    };

    let response = client
        .post(&url)
        .json(&request)
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
