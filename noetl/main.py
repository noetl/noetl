import uvicorn
import typer
import os
import json
import logging
import base64
import requests
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from noetl.server import router as server_router
from noetl.system import router as system_router
from noetl.common import deep_merge, DateTimeEncoder
from noetl.logger import setup_logger
from noetl.worker import Worker
from noetl.schema import DatabaseSchema

logger = setup_logger(__name__, include_location=True)

cli_app = typer.Typer()

_enable_ui = True

def create_app() -> FastAPI:
    global _enable_ui

    return _create_app(_enable_ui)

def _create_app(enable_ui: bool = True) -> FastAPI:
    app = FastAPI(
        title="NoETL API",
        description="NoETL API server",
        version="0.1.21"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    try:
        logger.info("Initializing NoETL system metadata.")
        db_schema = DatabaseSchema(auto_setup=False)
        db_schema.create_noetl_metadata()
        db_schema.init_database()
        logger.info("NoETL user and database schema initialized.")
    except Exception as e:
        logger.error(f"Error initializing NoETL system metadata: {e}", exc_info=True)
        logger.warning("Database connection failed. Some features requiring database access will be limited.")
        logger.warning("Playbook registration will work in memory-only mode.")
        logger.warning("Continuing with server startup despite database initialization error.")

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



@cli_app.command("server")
def run_server(
    host: str = typer.Option("0.0.0.0", help="Server host."),
    port: int = typer.Option(8080, help="Server port."),
    reload: bool = typer.Option(False, help="Server auto-reload."),
    no_ui: bool = typer.Option(False, "--no-ui", help="Disable the UI components."),
    debug: bool = typer.Option(False, "--debug", help="Enable debug logging mode.")
):
    global _enable_ui

    if not no_ui and os.environ.get("NOETL_ENABLE_UI", "true").lower() == "false":
        no_ui = True

    _enable_ui = not no_ui

    log_level = "debug" if debug else "info"
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.DEBUG if debug else logging.INFO
    )

    ui_status = "disabled" if no_ui else "enabled"
    debug_status = "enabled" if debug else "disabled"
    logger.info(f"Starting NoETL API server at http://{host}:{port} (UI {ui_status}, Debug {debug_status})")
    
    logger.info("=== ENVIRONMENT VARIABLES AT SERVER STARTUP ===")
    for key, value in sorted(os.environ.items()):
        logger.info(f"ENV: {key}={value}")
    logger.info("=== END ENVIRONMENT VARIABLES ===")
    
    uvicorn.run("noetl.main:create_app", factory=True, host=host, port=port, reload=reload, log_level=log_level)


@cli_app.command("agent")
def run_agent(
    file: str = typer.Option(..., "--file", "-f", help="Path to playbooks YAML file."),
    mock: bool = typer.Option(False, help="Run in mock mode"),
    output: str = typer.Option("json", "--output", "-o", help="Output format, json or plain."),
    export: str = typer.Option(None, help="Export execution data to Parquet file."),
    mlflow: bool = typer.Option(False, help="Use ML model for workflow control."),
    postgres: str = typer.Option(None, help="Postgres connection string."),
    duckdb: str = typer.Option(None, help="Path to DuckDB file for business logic in playbooks."),
    input: str = typer.Option(None, help="Path to the input payload JSON file for the playbooks."),
    payload: str = typer.Option(None, help="JSON input payload string for the playbooks."),
    merge: bool = typer.Option(False, help="Merge the input payload with the workload section."),
    debug: bool = typer.Option(False, "--debug", help="Debug logging mode.")
):
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.DEBUG if debug else logging.INFO
    )

    try:
        input_payload = None
        if input:
            try:
                with open(input, 'r') as f:
                    input_payload = json.load(f)
                logger.info(f"Loaded input payload from {input}")
            except Exception as e:
                logger.error(f"Error loading input payload: {e}")
                raise typer.Exit(code=1)
        elif payload:
            try:
                input_payload = json.loads(payload)
                logger.info("Parsed input payload from command line")
            except Exception as e:
                logger.error(f"Error parsing payload JSON: {e}")
                raise typer.Exit(code=1)
        pgdb_conn = postgres or os.environ.get("NOETL_PGDB")
        if not pgdb_conn:
            pgdb_conn = f"dbname={os.environ.get('POSTGRES_DB', 'demo_noetl')} user={os.environ.get('POSTGRES_USER', 'demo')} password={os.environ.get('POSTGRES_PASSWORD', 'demo')} host={os.environ.get('POSTGRES_HOST', 'localhost')} port={os.environ.get('POSTGRES_PORT', '5432')} hostaddr='' gssencmode=disable"
            logger.info(f"Using default Postgres connection string: {pgdb_conn}")

        if duckdb:
            os.environ['DUCKDB_PATH'] = duckdb
            logger.info(f"Using DuckDB for business logic: {duckdb}")

        agent = Worker(file, mock_mode=mock, pgdb=pgdb_conn)
        workload = agent.playbook.get('workload', {})

        if input_payload:
            if merge:
                logger.info("Merge mode: deep merging input payload with workload.")
                merged_workload = deep_merge(workload, input_payload)
                for key, value in merged_workload.items():
                    agent.update_context(key, value)
                agent.update_context('workload', merged_workload)
                agent.store_workload(merged_workload)
            else:
                logger.info("Override mode: replacing the matching workload keys with input payload.")
                new_workload = workload.copy()
                for key, value in input_payload.items():
                    new_workload[key] = value
                for key, value in new_workload.items():
                    agent.update_context(key, value)
                agent.update_context('workload', new_workload)
                agent.store_workload(new_workload)
        else:
            logger.info("Using default workload from playbooks.")
            for key, value in workload.items():
                agent.update_context(key, value)
            agent.update_context('workload', workload)
            agent.store_workload(workload)

        results = agent.run(mlflow=mlflow)

        if export:
            agent.export_execution_data(export)

        if output == "json":
            logger.info(json.dumps(results, indent=2))
        else:
            for step, result in results.items():
                logger.info(f"{step}: {result}")

        logger.info(f"Postgres connection: {agent.pgdb}")
        logger.info(f"Open notebook/agent_mission_report.ipynb and set 'pgdb' to {agent.pgdb}")

    except Exception as e:
        logger.error(f"Error executing playbooks: {e}", exc_info=True)
        print(f"Error executing playbooks: {e}")
        raise typer.Exit(code=1)


@cli_app.command("catalog")
def manage_catalog(
    action: str = typer.Argument(help="Action to perform: register, execute, list"),
    resource_type_or_path: str = typer.Argument(help="Resource type (for list) or path (for register/execute)"),
    path: str = typer.Argument(None, help="Path to resource file (for register) or resource path (for execute) - optional if type is inferred"),
    version: str = typer.Option(None, "--version", "-v", help="Version of the resource to execute."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str = typer.Option("localhost", "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(8080, "--port", "-p", help="NoETL server port."),
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
        if os.path.exists(resource_type_or_path):
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
                            if status == 'success':
                                success_count += 1
                                print(f"✓ {step_name}: SUCCESS")
                            elif status == 'error':
                                error_count += 1
                                error_msg = step_result.get('error', 'Unknown error')
                                print(f"✗ {step_name}: ERROR - {error_msg}")
                            elif status == 'skipped':
                                skipped_count += 1
                                print(f"~ {step_name}: SKIPPED")
                            else:
                                print(f"? {step_name}: UNKNOWN STATUS")
                        else:
                            success_count += 1
                            print(f"✓ {step_name}: SUCCESS")

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
                params["resource_type"] = "Playbook"  # Use singular form

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
                        timestamp = timestamp.split('T')[0]  # Show only date
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
    playbook_path: str = typer.Argument(help="Path or name of the playbook to execute"),
    version: str = typer.Option(None, "--version", "-v", help="Version of the playbook to execute."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str = typer.Option("localhost", "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(8080, "--port", "-p", help="NoETL server port."),
    sync: bool = typer.Option(True, "--sync", help="Sync up execution data to Postgres."),
    merge: bool = typer.Option(False, "--merge", help="Merge the input payload with the workload section of playbook.")
):
    """
    Execute a playbook (convenience command for 'noetl catalog execute playbook')

    Examples:
        noetl execute weather_example --version 0.1.0
        noetl execute tradetrend/batch_load --host localhost --port 8082
    """

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
            "path": playbook_path,
            "input_payload": input_payload,
            "sync_to_postgres": sync,
            "merge": merge
        }

        if version:
            data["version"] = version

        if version:
            logger.info(f"Executing playbook {playbook_path} version {version} on NoETL server at {url}")
        else:
            logger.info(f"Executing playbook {playbook_path} (latest version) on NoETL server at {url}")
        response = requests.post(url, headers=headers, json=data)

        if response.status_code == 200:
            result = response.json()
            logger.info(f"Playbook executed.")

            if result.get("status") == "success":
                logger.info(f"Execution ID: {result.get('execution_id')}")
                execution_result = result.get('result', {})
                logger.debug(f"Full execution result: {json.dumps(execution_result, indent=2, cls=DateTimeEncoder)}")

                print("\n" + "="*80)
                print("EXECUTION REPORT")
                print("="*80)
                print(f"Playbook Path: {playbook_path}")
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
                        if status == 'success':
                            success_count += 1
                            print(f"✓ {step_name}: SUCCESS")
                        elif status == 'error':
                            error_count += 1
                            error_msg = step_result.get('error', 'Unknown error')
                            print(f"✗ {step_name}: ERROR - {error_msg}")
                        elif status == 'skipped':
                            skipped_count += 1
                            print(f"~ {step_name}: SKIPPED")
                        else:
                            print(f"? {step_name}: UNKNOWN STATUS")
                    else:
                        success_count += 1
                        print(f"✓ {step_name}: SUCCESS")

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
            logger.error(f"Failed to execute playbook: {response.status_code}")
            logger.error(f"Response: {response.text}")
            raise typer.Exit(code=1)

    except Exception as e:
        logger.error(f"Error executing playbook: {e}")
        raise typer.Exit(code=1)


@cli_app.command("register")
def register_playbook(
    playbook_file: str = typer.Argument(help="Path to playbook file to register"),
    host: str = typer.Option("localhost", "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(8080, "--port", "-p", help="NoETL server port.")
):
    """
    Register a playbook (convenience command for 'noetl catalog register playbook')

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
            "resource_type": "Playbook"  # Use singular form
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
def main():
    cli_app()
app = create_app()

if __name__ == "__main__":
    main()
