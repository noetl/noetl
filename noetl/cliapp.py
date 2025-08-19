import os
import json
import logging
import base64
import requests
import tempfile
import signal
import time
from pathlib import Path
import typer
import uvicorn
from typing import Optional
from noetl.logger import setup_logger
from noetl.common import DateTimeEncoder
from noetl.schema import DatabaseSchema
from noetl.worker import Worker
from noetl.config import settings
from noetl.diagram import render_plantuml_file, render_image_kroki

logger = setup_logger(__name__, include_location=True)

def _validate_required_env():
    required_vars = [
        "NOETL_USER",
        "NOETL_PASSWORD",
        "NOETL_SCHEMA",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "NOETL_ENCRYPTION_KEY",
    ]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise typer.Exit(code=1)

cli_app = typer.Typer()
secret_app = typer.Typer()
cli_app.add_typer(secret_app, name="secret")

@secret_app.command("register")
def register_secret(
    name: str = typer.Option(..., "--name", "-n", help="Credential name (unique)"),
    type_: str = typer.Option(..., "--type", "-t", help="Credential type, e.g., httpBearerAuth"),
    data: str = typer.Option(None, "--data", help="JSON string with credential data"),
    data_file: str = typer.Option(None, "--data-file", help="Path to JSON file with credential data"),
    meta: str = typer.Option(None, "--meta", help="Optional JSON string for metadata"),
    meta_file: str = typer.Option(None, "--meta-file", help="Path to JSON file for metadata"),
    tags: str = typer.Option(None, "--tags", help="Comma-separated list of tags"),
    description: str = typer.Option(None, "--description", "-d", help="Description"),
    host: str = typer.Option(os.environ.get("NOETL_HOST", "localhost"), "--host", help="NoETL server host"),
    port: int = typer.Option(int(os.environ.get("NOETL_PORT", "8080")), "--port", "-p", help="NoETL server port"),
):
    """
    Register or update a secret/credential in NoETL.
    """
    try:
        payload_data = None
        if data_file:
            try:
                with open(data_file, "r") as f:
                    payload_data = json.load(f)
            except Exception as e:
                typer.echo(f"Error reading data file: {e}")
                raise typer.Exit(code=1)
        elif data:
            try:
                payload_data = json.loads(data)
            except Exception as e:
                typer.echo(f"Invalid JSON for --data: {e}")
                raise typer.Exit(code=1)
        else:
            typer.echo("Either --data or --data-file must be provided")
            raise typer.Exit(code=1)

        meta_obj = None
        if meta_file:
            try:
                with open(meta_file, "r") as f:
                    meta_obj = json.load(f)
            except Exception as e:
                typer.echo(f"Error reading meta file: {e}")
                raise typer.Exit(code=1)
        elif meta:
            try:
                meta_obj = json.loads(meta)
            except Exception as e:
                typer.echo(f"Invalid JSON for --meta: {e}")
                raise typer.Exit(code=1)

        tags_list = None
        if tags:
            tags_list = [t.strip() for t in tags.split(',') if t.strip()]

        url = f"http://{host}:{port}/api/credentials"
        body = {
            "name": name,
            "type": type_,
            "data": payload_data,
            "meta": meta_obj,
            "tags": tags_list,
            "description": description,
        }
        headers = {"Content-Type": "application/json"}
        resp = requests.post(url, json=body, headers=headers)
        if resp.status_code == 200:
            typer.echo("Secret registered successfully:")
            typer.echo(json.dumps(resp.json(), indent=2, cls=DateTimeEncoder))
        else:
            typer.echo(f"Registration failed: {resp.status_code}")
            typer.echo(resp.text)
            raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Error registering secret: {e}")
        raise typer.Exit(code=1)

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
    debug: bool = typer.Option(settings.debug, help="Enable debug logging mode"),
    server: str = typer.Option("uvicorn", help="Server type: uvicorn, gunicorn, or auto")
):
    """
    Start the NoETL server.
    """
    _validate_required_env()

    settings.host = host
    settings.port = port
    settings.debug = debug
    settings.enable_ui = not no_ui

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

    max_startup_wait_secs = int(os.environ.get("NOETL_DB_STARTUP_TIMEOUT", "180"))
    retry_interval_secs = int(os.environ.get("NOETL_DB_RETRY_INTERVAL", "5"))
    start_time = time.time()
    initialized = False
    last_error = None
    logger.info(
        f"Initializing NoETL system metadata (will retry up to {max_startup_wait_secs}s, interval {retry_interval_secs}s)"
    )
    while time.time() - start_time < max_startup_wait_secs and not initialized:
        try:
            db_schema = DatabaseSchema(auto_setup=False)
            db_schema.create_noetl_metadata()
            db_schema.init_database()
            logger.info("NoETL database schema initialized.")
            initialized = True
        except Exception as e:
            last_error = e
            logger.warning(
                f"Database not ready or initialization failed: {e}. Retrying in {retry_interval_secs}s...",
                exc_info=False,
            )
            time.sleep(retry_interval_secs)
    if not initialized:
        logger.error(
            f"Error initializing NoETL system metadata after {max_startup_wait_secs}s: {last_error}",
            exc_info=True,
        )
        logger.error("Continuing to start API without completed DB initialization. Some endpoints may fail until DB is ready.")

    server_type = server
    if server == "auto":
        try:
            import gunicorn  # noqa: F401
            server_type = "gunicorn"
            logger.info("Auto-detected Gunicorn as the server runtime.")
        except ImportError:
            server_type = "uvicorn"
            logger.info("Auto-detected Uvicorn as the server runtime (Gunicorn not available).")

    os.makedirs(PID_FILE_DIR, exist_ok=True)
    with open(PID_FILE_PATH, 'w') as f:
        f.write(str(os.getpid()))
    logger.info(f"Server PID {os.getpid()} saved to {PID_FILE_PATH}")

    try:
        if server_type == "gunicorn":
            _run_with_gunicorn(host, port, workers, reload, log_level)
        else:
            _run_with_uvicorn(host, port, workers, reload, log_level)
    finally:
        if os.path.exists(PID_FILE_PATH):
            os.remove(PID_FILE_PATH)
            logger.info(f"Removed PID file {PID_FILE_PATH}")

def _run_with_uvicorn(host: str, port: int, workers: int, reload: bool, log_level: str):
    uvicorn.run("noetl.main:create_app", factory=True, host=host, port=port, workers=workers, reload=reload, log_level=log_level)

def _run_with_gunicorn(host: str, port: int, workers: int, reload: bool, log_level: str):
    try:
        import subprocess
        import sys

        cmd = [
            sys.executable, "-m", "gunicorn",
            "noetl.main:create_app()",
            "--bind", f"{host}:{port}",
            "--workers", str(workers),
            "--worker-class", "uvicorn.workers.UvicornWorker",
            "--log-level", log_level
        ]

        if reload:
            cmd.extend(["--reload"])

        logger.info(f"Starting Gunicorn with command: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)

    except ImportError:
        logger.error("Gunicorn is not installed. Please install it with: pip install gunicorn")
        logger.info("Falling back to Uvicorn...")
        _run_with_uvicorn(host, port, workers, reload, log_level)
    except Exception as e:
        logger.error(f"Error running Gunicorn: {e}")
        logger.info("Falling back to Uvicorn...")
        _run_with_uvicorn(host, port, workers, reload, log_level)

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
    debug: bool = typer.Option(settings.debug, "--debug", help="Enable debug logging mode."),
    server: str = typer.Option("uvicorn", help="Server type: uvicorn, gunicorn, or auto")
):
    """
    Start the NoETL server for backward compatibility.
    Maps to 'noetl server start' command.
    """
    start_server(host=host, port=port, workers=1, reload=reload, no_ui=no_ui, debug=debug, server=server)

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
    Manage catalog resources.
    """

    auto_detect_mode = False

    if action == "register":
        if resource_type_or_path == "playbook" and path and os.path.exists(path):
            resource_type = "playbook"
            file_path = path
            detected_resource_type = "Playbook"
            auto_detect_mode = False
            logger.info(f"Using explicit resource type: {resource_type} for file: {file_path}")
        elif resource_type_or_path == "secret" and path and os.path.exists(path):
            resource_type = "secret"
            file_path = path
            detected_resource_type = "Secret"
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
                    elif kind in ("secret", "credential"):
                        resource_type = "secret"
                        detected_resource_type = "Secret"
                    else:
                        logger.error(f"Unsupported resource kind: {kind}. Supported kinds: Playbook, Secret/Credential")
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

            if detected_resource_type == "Secret":
                try:
                    import yaml
                    resource_data = yaml.safe_load(content)
                except Exception as e:
                    logger.error(f"Failed to parse secret file {file_path}: {e}")
                    raise typer.Exit(code=1)

                name = resource_data.get("name") or (resource_data.get("metadata", {}) or {}).get("name")
                ctype = resource_data.get("type") or (resource_data.get("spec", {}) or {}).get("type")
                data_obj = resource_data.get("data") or (resource_data.get("spec", {}) or {}).get("data")
                meta_obj = resource_data.get("meta") or (resource_data.get("spec", {}) or {}).get("meta")
                tags_obj = resource_data.get("tags") or (resource_data.get("spec", {}) or {}).get("tags")
                description = resource_data.get("description") or (resource_data.get("spec", {}) or {}).get("description")

                if not name or not ctype or data_obj is None:
                    logger.error("Secret manifest must contain at least 'name', 'type', and 'data'.")
                    raise typer.Exit(code=1)

                url = f"http://{host}:{port}/api/credentials"
                headers = {"Content-Type": "application/json"}
                data = {
                    "name": name,
                    "type": ctype,
                    "data": data_obj,
                    "meta": meta_obj,
                    "tags": tags_obj,
                    "description": description,
                }

                if auto_detect_mode:
                    logger.info(f"Registering secret {file_path} (auto-detected) with NoETL server at {url}")
                else:
                    logger.info(f"Registering secret {file_path} with NoETL server at {url}")

                response = requests.post(url, headers=headers, json=data)

                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Secret registered successfully: {result}")
                else:
                    logger.error(f"Failed to register secret: {response.status_code}")
                    logger.error(f"Response: {response.text}")
                    raise typer.Exit(code=1)
            else:
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

                if result.get("execution_id"):
                    logger.info(f"Execution ID: {result.get('execution_id')}")
                    execution_result = result.get('result', {})
                    logger.debug(f"Full execution result: {json.dumps(execution_result, indent=2, cls=DateTimeEncoder)}")

                    any_errors = any(
                        isinstance(step_result, dict) and step_result.get('status') == 'error'
                        for step_name, step_result in execution_result.items()
                    )

                    print("\n" + "="*80)
                    print("EXECUTION REPORT")
                    print("="*80)
                    print(f"{resource_type.capitalize()} Path: {path}")
                    print(f"Version: {version or 'latest'}")
                    print(f"Execution ID: {result.get('execution_id')}")

                    if any_errors:
                        print(f"Status: FAILED")
                    else:
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
                elif not result.get("execution_id"):
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
    """
    _validate_required_env()

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


@cli_app.command("diagram")
def diagram_playbook(
    playbook_file: str = typer.Argument(..., help="Path to playbook YAML or .puml file."),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path. For plantuml, writes text; for svg/png, writes bytes."),
    format: str = typer.Option("plantuml", "--format", "-f", help="Diagram format: plantuml | svg | png")
):
    """Generate a DAG diagram for a NoETL playbook (PlantUML text or image via Kroki)."""
    try:
        fmt = (format or "plantuml").lower()

        if playbook_file.lower().endswith((".puml", ".plantuml")):
            with open(playbook_file, "r") as f:
                puml = f.read()
        else:
            puml = render_plantuml_file(playbook_file)

        if fmt == "plantuml":
            if output:
                with open(output, "w") as f:
                    f.write(puml)
                typer.echo(f"PlantUML written to {output}")
            else:
                typer.echo(puml)
            return

        if fmt in ("svg", "png"):
            out_path = output
            if not out_path:
                base, _ = os.path.splitext(playbook_file)
                out_path = f"{base}.{fmt}"
                typer.echo(f"No --output provided; writing to {out_path}")
            img_bytes = render_image_kroki(puml, fmt=fmt)
            with open(out_path, "wb") as f:
                f.write(img_bytes)
            typer.echo(f"{fmt.upper()} written to {out_path}")
            return

        typer.echo(f"Unsupported format: {format}. Use one of: plantuml, svg, png")
        raise typer.Exit(code=1)

    except Exception as e:
        typer.echo(f"Error generating diagram: {e}")
        raise typer.Exit(code=1)
