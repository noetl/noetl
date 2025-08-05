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
        version="0.1.35"
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



@cli_app.command("server")
def run_server(
    host: str = typer.Option(os.environ.get("NOETL_HOST", "0.0.0.0"), help="Server host."),
    port: int = typer.Option(int(os.environ.get("NOETL_PORT", "8080")), help="Server port."),
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
    
    try:
        logger.info("Initializing NoETL system metadata.")
        db_schema = DatabaseSchema(auto_setup=True)
        db_schema.create_noetl_metadata()
        db_schema.init_database()
        logger.info("NoETL database schema initialized.")
    except Exception as e:
        logger.error(f"Error initializing NoETL system metadata: {e}", exc_info=True)
        logger.error("Database connection failed. Cannot start NoETL server.")
        logger.error("Please check database configuration.")
        raise typer.Exit(code=1)

    uvicorn.run("noetl.main:create_app", factory=True, host=host, port=port, reload=reload, log_level=log_level)


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
    playbook_path: str = typer.Argument(help="Path or name of the playbook to execute"),
    version: str = typer.Option(None, "--version", "-v", help="Version of the playbook to execute."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str = typer.Option(os.environ.get("NOETL_HOST", "localhost"), "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(int(os.environ.get("NOETL_PORT", "8080")), "--port", "-p", help="NoETL server port."),
    sync: bool = typer.Option(True, "--sync", help="Sync up execution data to Postgres."),
    merge: bool = typer.Option(False, "--merge", help="Merge the input payload with the workload section of playbook.")
):
    """
    Execute a playbook for 'noetl catalog execute playbook'

    Examples:
        noetl execute example/weather/weather_example --version 0.1.0
        noetl execute example/batch/batch_load --host localhost --port 8082
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
                        print(f"{step_name}: COMPLETED (status unclear)")
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
            logger.error(f"Failed to execute playbook: {response.status_code}")
            logger.error(f"Response: {response.text}")
            raise typer.Exit(code=1)

    except Exception as e:
        logger.error(f"Error executing playbook: {e}")
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
def main():
    cli_app()
app = create_app()

if __name__ == "__main__":
    main()
