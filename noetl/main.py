import uvicorn
import typer
import os
import json
import logging
import base64
import requests
import tempfile
import signal
import time
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from noetl.server import router as server_router
from noetl.system import router as system_router
from noetl.common import deep_merge, DateTimeEncoder
from noetl.logger import setup_logger
from noetl.schema import DatabaseSchema
from noetl.worker import Worker
from noetl.config import settings

logger = setup_logger(__name__, include_location=True)

cli_app = typer.Typer()

_enable_ui = True

def create_app() -> FastAPI:
    global _enable_ui
    
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.INFO
    )
    
    print("=== ENVIRONMENT VARIABLES AT SERVER STARTUP ===")
    for key, value in sorted(os.environ.items()):
        print(f"ENV: {key}={value}")
    print("=== END ENVIRONMENT VARIABLES ===")
    
    return _create_app(_enable_ui)

def _create_app(enable_ui: bool = True) -> FastAPI:

    app = FastAPI(
        title="NoETL API",
        description="NoETL API server",
        version="0.1.37"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    package_dir = Path(__file__).parent
    ui_build_path = package_dir / "ui" / "build"

    app.include_router(server_router, prefix="/api")
    app.include_router(system_router, prefix="/api/sys", tags=["System"])

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    if enable_ui and ui_build_path.exists():
        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            favicon_file = ui_build_path / "favicon.ico"
            if favicon_file.exists():
                return FileResponse(favicon_file)
            return FileResponse(ui_build_path / "index.html")
        
        app.mount("/assets", StaticFiles(directory=ui_build_path / "assets"), name="assets")
        
        @app.get("/{catchall:path}", include_in_schema=False)
        async def spa_catchall(catchall: str):
            return FileResponse(ui_build_path / "index.html")
        
        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(ui_build_path / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def root_no_ui():
            return {"message": "NoETL API is running, but UI is not available"}

    return app



server_app = typer.Typer()
cli_app.add_typer(server_app, name="server")

PID_FILE_DIR = os.path.expanduser("~/.noetl")
PID_FILE_PATH = os.path.join(PID_FILE_DIR, "noetl_server.pid")

@server_app.command("start")
def start_server(
    host: str = typer.Option(settings.host, help="Host to bind the server"),
    port: int = typer.Option(settings.port, help="Port to bind the server"),
    workers: int = typer.Option(1, help="Number of worker processes"),
    reload: bool = typer.Option(False, help="Enable auto-reload (development mode)"),
    no_ui: bool = typer.Option(not settings.enable_ui, "--no-ui", help="Disable the UI components"),
    debug: bool = typer.Option(settings.debug, help="Enable debug logging mode")
):
    """
    Start the NoETL server using Uvicorn.
    """
    global _enable_ui

    settings.host = host
    settings.port = port
    settings.debug = debug
    settings.enable_ui = not no_ui

    _enable_ui = settings.enable_ui

    log_level = "debug" if settings.debug else "info"
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.DEBUG if settings.debug else logging.INFO
    )

    ui_status = "disabled" if not settings.enable_ui else "enabled"
    debug_status = "enabled" if settings.debug else "disabled"
    logger.info(f"Starting NoETL API server at http://{settings.host}:{settings.port} (UI {ui_status}, Debug {debug_status}, Workers: {workers})")

    logger.info("=== ENVIRONMENT VARIABLES AT SERVER STARTUP ===")
    for key, value in sorted(os.environ.items()):
        logger.info(f"ENV: {key}={value}")
    logger.info("=== END ENVIRONMENT VARIABLES ===")

    try:
        logger.info("Initializing NoETL system metadata.")
        db_schema = DatabaseSchema(auto_setup=False)
        db_schema.create_noetl_metadata()
        db_schema.init_database()
        logger.info("NoETL database schema initialized.")
    except Exception as e:
        logger.error(f"Error initializing NoETL system metadata: {e}", exc_info=True)
        logger.error("Database connection failed. Cannot start NoETL server.")
        logger.error("Please check database configuration.")
        raise typer.Exit(code=1)

    logger.info("Using Uvicorn as the server runtime.")
    
    os.makedirs(PID_FILE_DIR, exist_ok=True)
    
    with open(PID_FILE_PATH, 'w') as f:
        f.write(str(os.getpid()))
    logger.info(f"Server PID {os.getpid()} saved to {PID_FILE_PATH}")
    
    try:
        uvicorn.run("noetl.main:create_app", factory=True, host=host, port=port, workers=workers, reload=reload, log_level=log_level)
    finally:
        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)
            logger.info(f"Removed PID file {PID_FILE_PATH}")

@server_app.command("stop")
def stop_server(
    force: bool = typer.Option(False, "--force", "-f", help="Force stop the server without confirmation")
):
    """
    Stop the running NoETL server.
    """
    if not os.path.exists(PID_FILE_PATH):
        typer.echo("No running NoETL server found.")
        return
    
    try:
        with open(PID_FILE_PATH, 'r') as f:
            pid = int(f.read().strip())
        
        try:
            os.kill(pid, 0)
            
            if not force:
                confirm = typer.confirm(f"Stop NoETL server with PID {pid}?")
                if not confirm:
                    typer.echo("Operation cancelled.")
                    return
            
            typer.echo(f"Stopping NoETL server with PID {pid}...")
            
            os.kill(pid, signal.SIGTERM)
            
            for _ in range(10):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.5)
                except OSError:
                    break
            else:
                if force or typer.confirm("Server didn't stop gracefully. Force kill?"):
                    typer.echo(f"Force killing NoETL server with PID {pid}...")
                    os.kill(pid, signal.SIGKILL)
            
            if os.path.exists(PID_FILE_PATH):
                os.remove(PID_FILE_PATH)
            
            typer.echo("NoETL server stopped successfully.")
            
        except OSError:
            typer.echo(f"No process found with PID {pid}. The server may have been stopped already.")
            os.remove(PID_FILE_PATH)
            
    except Exception as e:
        typer.echo(f"Error stopping NoETL server: {e}")
        raise typer.Exit(code=1)

@cli_app.command("server", hidden=True)
def run_server(
    host: str = typer.Option(settings.host, help="Server host."),
    port: int = typer.Option(settings.port, help="Server port."),
    reload: bool = typer.Option(False, help="Server auto-reload."),
    no_ui: bool = typer.Option(not settings.enable_ui, "--no-ui", help="Disable the UI components."),
    debug: bool = typer.Option(settings.debug, "--debug", help="Enable debug logging mode.")
):
    """
    [DEPRECATED] Use 'noetl server start' instead.
    """
    typer.echo("Warning: 'noetl server' is deprecated. Use 'noetl server start' instead.")
    start_server(host=host, port=port, workers=1, reload=reload, no_ui=no_ui, debug=debug)


@cli_app.command("catalog")
def manage_catalog(
    action: str = typer.Argument(help="Action to perform: register, execute, list"),
    resource_type_or_path: str = typer.Argument(help="Resource type (for list) or path (for register/execute)"),
    path: str = typer.Argument(None, help="Path to resource file (for register) or resource path (for execute) - optional if type is inferred"),
    version: str = typer.Option(None, "--version", "-v", help="Version of the resource to execute."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str = typer.Option(os.environ.get("NOETL_HOST", "localhost"), "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(int(os.environ.get("NOETL_PORT", "8080")), "--port", "-p", help="NoETL server port."),
    sync: bool = typer.Option(True, "--sync", help="Sync up execution data to Postgres."),
    merge: bool = typer.Option(False, "--merge", help="Merge the input payload with the workload section of resource.")
):
    """
    Manage catalog resources playbooks, datasets, notebooks, models, etc.

    Examples:
        # Auto-detect resource type from file content:
        noetl catalog register /path/to/playbook.yaml

        # Explicit resource type (with validation):
        noetl catalog register playbook /path/to/playbook.yaml

        # Execute and list:
        noetl catalog execute weather_example --version 0.1.0
        noetl catalog list playbook
    """

    auto_detect_mode = False

    if action == "register":
        if resource_type_or_path == "playbook" and path and os.path.exists(path):
            resource_type = "playbook"
            file_path = path
            detected_resource_type = "Playbook"
            auto_detect_mode = False
            logger.info(f"Using explicit resource type: {resource_type} for file: {file_path}")
        elif os.path.exists(resource_type_or_path):
            auto_detect_mode = True
            file_path = resource_type_or_path

            try:
                with open(file_path, 'r') as f:
                    content = f.read()
                    import yaml
                    resource_data = yaml.safe_load(content)
                    kind = resource_data.get("kind", "").lower()

                    if kind == "playbook":
                        resource_type = "playbook"
                        detected_resource_type = "Playbook"
                    else:
                        logger.error(f"Unsupported resource kind: {kind}. Supported kinds: Playbook")
                        raise typer.Exit(code=1)

                logger.info(f"Auto-detected resource type: {resource_type} from kind: {resource_data.get('kind')}")

            except Exception as e:
                logger.error(f"Error reading or parsing file {file_path}: {e}")
                raise typer.Exit(code=1)
        else:
            resource_type = resource_type_or_path
            file_path = path
            detected_resource_type = "Playbook"

            if not file_path:
                logger.error("Path to resource file is required when using explicit resource type")
                logger.info(f"Example: noetl catalog register {resource_type} /path/to/file.yaml")
                raise typer.Exit(code=1)
    else:
        if action == "execute":
            resource_path = resource_type_or_path
        elif action == "list":
            resource_type = resource_type_or_path
            if resource_type not in ["playbook"]:
                logger.error(f"Unsupported resource type: {resource_type}. Supported types: playbook")
                raise typer.Exit(code=1)

    if action == "register":
        try:
            if not os.path.exists(file_path):
                logger.error(f"File not found: {file_path}")
                raise typer.Exit(code=1)
            with open(file_path, 'r') as f:
                content = f.read()
            content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            url = f"http://{host}:{port}/api/catalog/register"
            headers = {"Content-Type": "application/json"}
            data = {
                "content_base64": content_base64,
                "resource_type": detected_resource_type
            }

            if auto_detect_mode:
                logger.info(f"Registering {resource_type} {file_path} (auto-detected) with NoETL server at {url}")
            else:
                logger.info(f"Registering {resource_type} {file_path} with NoETL server at {url}")

            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"{resource_type.capitalize()} registered successfully: {result}")
                logger.info(f"Resource path: {result.get('resource_path')}")
                logger.info(f"Resource version: {result.get('resource_version')}")
            else:
                logger.error(f"Failed to register {resource_type}: {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error registering {resource_type}: {e}")
            raise typer.Exit(code=1)

    elif action == "execute":
        if not path:
            logger.error("Resource path is required for execute action")
            logger.info(f"Example: noetl catalog execute {resource_type} weather_example --version 0.1.0")
            raise typer.Exit(code=1)

        try:
            input_payload = {}
            if input:
                try:
                    with open(input, 'r') as f:
                        input_payload = json.load(f)
                    logger.info(f"Loaded input payload from {input}")
                except Exception as e:
                    logger.error(f"Error loading input payload from file: {e}")
                    raise typer.Exit(code=1)
            elif payload:
                try:
                    input_payload = json.loads(payload)
                    logger.info("Parsed input payload from command line")
                except Exception as e:
                    logger.error(f"Error parsing payload JSON: {e}")
                    raise typer.Exit(code=1)

            url = f"http://{host}:{port}/api/agent/execute"
            headers = {"Content-Type": "application/json"}
            data = {
                "path": path,
                "input_payload": input_payload,
                "sync_to_postgres": sync,
                "merge": merge
            }

            if version:
                data["version"] = version

            if version:
                logger.info(f"Executing {resource_type} {path} version {version} on NoETL server at {url}")
            else:
                logger.info(f"Executing {resource_type} {path} (latest version) on NoETL server at {url}")
            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"{resource_type.capitalize()} executed.")

                if result.get("status") == "success":
                    logger.info(f"Execution ID: {result.get('execution_id')}")
                    execution_result = result.get('result', {})
                    logger.debug(f"Full execution result: {json.dumps(execution_result, indent=2, cls=DateTimeEncoder)}")

                    print("\n" + "="*80)
                    print("EXECUTION REPORT")
                    print("="*80)
                    print(f"{resource_type.capitalize()} Path: {path}")
                    print(f"Version: {version or 'latest'}")
                    print(f"Execution ID: {result.get('execution_id')}")
                    print(f"Status: SUCCESS")
                    print("-"*80)

                    step_count = 0
                    success_count = 0
                    error_count = 0
                    skipped_count = 0

                    for step_name, step_result in execution_result.items():
                        step_count += 1
                        if isinstance(step_result, dict):
                            status = step_result.get('status', None)
                            command_statuses = []

                            if status is None and any(key.startswith('command_') for key in step_result.keys()):
                                for key, value in step_result.items():
                                    if key.startswith('command_') and isinstance(value, dict):
                                        cmd_status = value.get('status')
                                        if cmd_status:
                                            command_statuses.append(cmd_status)

                            if command_statuses:
                                if all(s == 'success' for s in command_statuses):
                                    status = 'success'
                                elif any(s == 'error' for s in command_statuses):
                                    status = 'error'
                                else:
                                    status = 'partial'
                            else:
                                status = 'unknown'

                            if status == 'success':
                                success_count += 1
                                command_details = []
                                for key, value in step_result.items():
                                    if key.startswith('command_') and isinstance(value, dict):
                                        msg = value.get('message', 'Command executed')
                                        command_details.append(f"{key}: {msg}")

                                if command_details:
                                    print(f"{step_name}: SUCCESS ({len(command_details)} commands)")
                                else:
                                    print(f"{step_name}: SUCCESS")
                            elif status == 'error':
                                error_count += 1
                                error_details = []
                                for key, value in step_result.items():
                                    if key.startswith('command_') and isinstance(value, dict):
                                        if value.get('status') == 'error':
                                            error_msg = value.get('message', 'Unknown error')
                                            error_details.append(f"{key}: {error_msg}")

                                if error_details:
                                    print(f"{step_name}: ERROR - {'; '.join(error_details)}")
                                else:
                                    error_msg = step_result.get('error', 'Unknown error')
                                    print(f"{step_name}: ERROR - {error_msg}")
                            elif status == 'skipped':
                                skipped_count += 1
                                print(f"{step_name}: SKIPPED")
                            elif status == 'partial':
                                success_count += 1
                                print(f"{step_name}: PARTIAL SUCCESS")
                            else:
                                success_count += 1
                                print(f"{step_name}: COMPLETED with unclear status")
                        else:
                            success_count += 1
                            print(f"{step_name}: SUCCESS")

                    print("-"*80)
                    print(f"Total Steps: {step_count}")
                    print(f"Successful: {success_count}")
                    print(f"Failed: {error_count}")
                    print(f"Skipped: {skipped_count}")
                    print("="*80)
                else:
                    logger.error(f"Execution failed: {result.get('error')}")
                    raise typer.Exit(code=1)
            else:
                logger.error(f"Failed to execute {resource_type}: {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error executing {resource_type}: {e}")
            raise typer.Exit(code=1)

    elif action == "list":
        try:
            url = f"http://{host}:{port}/api/catalog/list"
            params = {}
            if resource_type == "playbook":
                params["resource_type"] = "Playbook"

            logger.info(f"Listing {resource_type}s from NoETL server at {url}")
            response = requests.get(url, params=params)

            if response.status_code == 200:
                result = response.json()
                entries = result.get("entries", [])

                if not entries:
                    print(f"No {resource_type}s found in catalog.")
                    return

                print(f"\n{resource_type.upper()}S IN CATALOG:")
                print("="*80)
                print(f"{'PATH':<40} {'VERSION':<10} {'TYPE':<15} {'TIMESTAMP':<15}")
                print("-"*80)

                for entry in entries:
                    path = entry.get('resource_path', 'Unknown')
                    version = entry.get('resource_version', 'Unknown')
                    res_type = entry.get('resource_type', 'Unknown')
                    timestamp = entry.get('timestamp', 'Unknown')
                    if isinstance(timestamp, str) and 'T' in timestamp:
                        timestamp = timestamp.split('T')[0]
                    print(f"{path:<40} {version:<10} {res_type:<15} {timestamp:<15}")
                print("="*80)
                print(f"Total: {len(entries)} {resource_type}(s)")

            else:
                logger.error(f"Failed to list {resource_type}s: {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error listing {resource_type}s: {e}")
            raise typer.Exit(code=1)
    else:
        logger.error(f"Unknown action: {action}. Supported actions: register, execute, list")
        logger.info("Examples:")
        logger.info(f"  noetl catalog register {resource_type} <path to file.yaml>")
        logger.info(f"  noetl catalog execute {resource_type} <resource name> --version 0.1.0")
        logger.info(f"  noetl catalog list {resource_type}")
        raise typer.Exit(code=1)
@cli_app.command("execute")
def execute_playbook(
    playbook_path: str = typer.Argument(..., help="Path or name of the playbook to execute."),
    version: str = typer.Option(None, "--version", "-v", help="Version of the playbook."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str = typer.Option("127.0.0.1", "--host", help="NoETL server host."),
    port: int = typer.Option(8080, "--port", help="NoETL server port."),
):
    """
    Execute a NoETL playbook via the REST API.
    
    This command sends a request to the NoETL server to execute the specified playbook.
    
    Examples:
        noetl execute my_playbook_path.yaml --version 1.0 --input payload.json
        noetl execute my_playbook --host 192.168.1.100 --port 8081
    """
    
    try:
        input_payload = {}
        if input:
            try:
                with open(input, "r") as file:
                    input_payload = json.load(file)
                typer.echo(f"Loaded input payload from {input}")
            except Exception as e:
                typer.echo(f"Error loading input payload from file: {e}")
                raise typer.Exit(code=1)
        elif payload:
            try:
                input_payload = json.loads(payload)
                typer.echo("Parsed input payload from command line")
            except Exception as e:
                typer.echo(f"Error parsing payload JSON: {e}")
                raise typer.Exit(code=1)

        url = f"http://{host}:{port}/api/agent/execute"
        request_data = {
            "path": playbook_path,
            "input_payload": input_payload
        }
        
        if version:
            request_data["version"] = version
            typer.echo(f"Executing playbook '{playbook_path}' version '{version}'")
        else:
            typer.echo(f"Executing playbook '{playbook_path}' (latest version)")
            
        typer.echo(f"Sending request to {url}")
        
        try:
            response = requests.post(url, json=request_data)
            
            if response.status_code == 200:
                result = response.json()
                typer.echo("Playbook executed successfully!")
                typer.echo(json.dumps(result, indent=2, cls=DateTimeEncoder))
            else:
                typer.echo(f"Execution failed: {response.status_code}")
                typer.echo(response.text)
                raise typer.Exit(code=1)
                
        except requests.RequestException as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(code=1)
            
    except Exception as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


@cli_app.command("register")
def register_playbook(
    playbook_file: str = typer.Argument(help="Path to playbook file to register"),
    host: str = typer.Option(os.environ.get("NOETL_HOST", "localhost"), "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(int(os.environ.get("NOETL_PORT", "8080")), "--port", "-p", help="NoETL server port.")
):
    """
    Register a playbook for 'noetl catalog register playbook'

    Examples:
        noetl register /path/to/playbook.yaml
        noetl register ./my_playbook.yaml --host localhost --port 8082
    """

    try:
        if not os.path.exists(playbook_file):
            logger.error(f"File not found: {playbook_file}")
            raise typer.Exit(code=1)
        with open(playbook_file, 'r') as f:
            content = f.read()
        content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
        url = f"http://{host}:{port}/api/catalog/register"
        headers = {"Content-Type": "application/json"}
        data = {
            "content_base64": content_base64,
            "resource_type": "Playbook"
        }
        logger.info(f"Registering playbook {playbook_file} with NoETL server at {url}")
        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"Playbook registered successfully: {result}")
            logger.info(f"Resource path: {result.get('resource_path')}")
            logger.info(f"Resource version: {result.get('resource_version')}")
        else:
            logger.error(f"Failed to register playbook: {response.status_code}")
            logger.error(f"Response: {response.text}")
            raise typer.Exit(code=1)

    except Exception as e:
        logger.error(f"Error registering playbook: {e}")
        raise typer.Exit(code=1)
@cli_app.command("cli")
def run_cli_mode():
    """
    Run NoETL in CLI mode.
    
    This command keeps the container running without starting a server or worker.
    It's used in containerized environments to execute CLI commands.
    
    Examples:
        noetl cli
    """
    import time
    
    typer.echo("NoETL container started in CLI mode")
    typer.echo("Use 'docker exec -it <container_name> noetl <command>' to run commands")
    
    try:
        while True:
            time.sleep(3600) 
    except KeyboardInterrupt:
        typer.echo("CLI mode terminated by user")
        
@cli_app.command("worker")
def run_worker(
    playbook_path: str = typer.Argument(..., help="Path or name of the playbook to execute as a worker"),
    version: str = typer.Option(settings.playbook_version, "--version", "-v", help="Version of the playbook to execute."),
    mock_mode: bool = typer.Option(settings.mock_mode, "--mock", help="Run in mock mode without executing real operations."),
    debug: bool = typer.Option(settings.debug, "--debug", help="Enable debug logging mode."),
    pgdb: str = typer.Option(None, "--pgdb", help="Postgres connection string. If not provided, uses environment variables.")
):
    """
    Run a worker process to execute a playbook.
    
    This command starts a worker process that executes the specified playbook.
    The worker runs independently from the server and can be used for background processing.
    
    Examples:
        noetl worker /path/to/playbook.yaml
        noetl worker playbook_name --version 0.1.0
        noetl worker playbook_name --mock
    """
    settings.playbook_path = playbook_path
    settings.playbook_version = version
    settings.mock_mode = mock_mode
    settings.debug = debug
    settings.run_mode = "worker"
    
    log_level = "debug" if settings.debug else "info"
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.DEBUG if settings.debug else logging.INFO
    )
    
    logger.info(f"Starting NoETL worker for playbook: {settings.playbook_path}")
    
    try:
        logger.info("Initializing NoETL system metadata.")
        db_schema = DatabaseSchema(auto_setup=True)
        logger.info("NoETL database schema initialized.")
        
        if version and not os.path.exists(playbook_path) and not playbook_path.endswith(('.yaml', '.yml', '.json')):
            logger.info(f"Fetching playbook '{playbook_path}' version '{version}' from catalog")
            from noetl.server import get_catalog_service
            catalog_service = get_catalog_service()
            entry = catalog_service.fetch_entry(playbook_path, version)
            if not entry:
                logger.error(f"Playbook '{playbook_path}' version '{version}' not found in catalog")
                raise typer.Exit(code=1)
            
            with tempfile.NamedTemporaryFile(suffix='.yaml', delete=False) as temp_file:
                temp_file.write(entry['content'].encode('utf-8'))
                temp_path = temp_file.name
            
            playbook_path = temp_path
            logger.info(f"Using temporary playbook file: {playbook_path}")
        
        worker = Worker(playbook_path=playbook_path, mock_mode=mock_mode, pgdb=pgdb)
        worker.run()
        logger.info("Worker execution completed successfully")
    except Exception as e:
        logger.error(f"Error running worker: {e}", exc_info=True)
        raise typer.Exit(code=1)

def main():
    cli_app()

if __name__ == "__main__":
    main()
