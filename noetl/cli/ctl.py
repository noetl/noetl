import uvicorn
import typer
import os
import json
import logging
import base64
import requests
import signal
import time
import asyncio
from noetl.worker import ScalableQueueWorkerPool, on_worker_terminate
from noetl.core.common import DateTimeEncoder
from noetl.core.logger import setup_logger
from noetl.core.dsl.schema import DatabaseSchema
from noetl.core.config import get_settings

logger = setup_logger(__name__, include_location=True)

cli_app = typer.Typer()

# from noetl.server import create_app
server_app = typer.Typer()
cli_app.add_typer(server_app, name="server")

worker_app = typer.Typer()
cli_appprefix = "worker"
cli_app.add_typer(worker_app, name=cli_appprefix)

# Database management
db_app = typer.Typer()
cli_app.add_typer(db_app, name="db")


@worker_app.command("start")
def start_worker_service(
    max_workers: int = typer.Option(None, "--max-workers", "-m", help="Maximum number of worker threads")
):
    """Start the queue worker pool that polls the server queue API."""

    from noetl.core.config import _settings
    import noetl.core.config as core_config
    core_config._settings = None
    core_config._ENV_LOADED = False
    
    # get_settings(reload=True)

    if not os.environ.get("NOETL_WORKER_POOL_RUNTIME"):
        os.environ["NOETL_WORKER_POOL_RUNTIME"] = "cpu"

    worker_name = os.environ.get("NOETL_WORKER_POOL_NAME") or f"worker-{os.environ.get('NOETL_WORKER_POOL_RUNTIME', 'cpu')}"
    worker_name = worker_name.replace("-", "_")  # Replace hyphens with underscores for filename
    
    pid_dir = os.path.expanduser("~/.noetl")
    os.makedirs(pid_dir, exist_ok=True)
    worker_pid_path = os.path.join(pid_dir, f"noetl_worker_{worker_name}.pid")
    with open(worker_pid_path, "w") as f:
        f.write(str(os.getpid()))
    logger.info(f"Worker PID {os.getpid()} saved to {worker_pid_path}")

    async def _run() -> None:
        pool_kwargs = {}
        if max_workers is not None:
            pool_kwargs['max_workers'] = max_workers
        pool = ScalableQueueWorkerPool(**pool_kwargs)
        loop = asyncio.get_running_loop()

        def _signal_handler(sig: int) -> None:
            logger.info(f"Worker pool received signal {sig}; shutting down")
            on_worker_terminate(sig)
            asyncio.create_task(pool.stop())

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, lambda s=sig: _signal_handler(s))

        await pool.run_forever()

    try:
        asyncio.run(_run())
    finally:
        if os.path.exists(worker_pid_path):
            os.remove(worker_pid_path)
            logger.info(f"Removed Worker PID file {worker_pid_path}")


@worker_app.command("stop")
def stop_worker_service(
    worker_name: str = typer.Option(None, "--name", "-n", help="Name of the worker to stop (if not specified, lists all workers)"),
    force: bool = typer.Option(False, "--force", "-f", help="Force stop the worker without confirmation")
):
    """
    Stop the running NoETL worker.
    This command should not require full environment configuration.
    """
    pid_dir = os.path.expanduser("~/.noetl")
    
    if worker_name:
        worker_name = worker_name.replace("-", "_")
        worker_pid_path = os.path.join(pid_dir, f"noetl_worker_{worker_name}.pid")
    else:
        worker_files = [f for f in os.listdir(pid_dir) if f.startswith("noetl_worker_") and f.endswith(".pid")]
        if not worker_files:
            typer.echo("No running NoETL worker services found.")
            return
        
        typer.echo("Running workers:")
        for i, f in enumerate(worker_files):
            worker_name = f.replace("noetl_worker_", "").replace(".pid", "")
            try:
                with open(os.path.join(pid_dir, f), 'r') as pf:
                    pid = pf.read().strip()
                typer.echo(f"  {i+1}. {worker_name} (PID: {pid})")
            except:
                typer.echo(f"  {i+1}. {worker_name} (PID file corrupted)")
        
        if len(worker_files) == 1:
            choice = 1
        else:
            choice = typer.prompt("Enter the number of the worker to stop", type=int)
        
        if choice < 1 or choice > len(worker_files):
            typer.echo("Invalid choice.")
            return
        
        worker_pid_path = os.path.join(pid_dir, worker_files[choice-1])

    if not os.path.exists(worker_pid_path):
        worker_name = worker_name or worker_pid_path.split("_")[-1].replace(".pid", "")
        typer.echo(f"No running NoETL worker '{worker_name}' found.")
        return

    try:
        with open(worker_pid_path, 'r') as f:
            pid = int(f.read().strip())

        try:
            os.kill(pid, 0)

            if not force:
                worker_name = worker_name or worker_pid_path.split("_")[-1].replace(".pid", "")
                confirm = typer.confirm(f"Stop NoETL worker '{worker_name}' with PID {pid}?")
                if not confirm:
                    typer.echo("Operation cancelled.")
                    return

            typer.echo(f"Stopping NoETL worker with PID {pid}...")
            os.kill(pid, signal.SIGTERM)

            for _ in range(20):  # Increased from 10 to 20
                try:
                    os.kill(pid, 0)
                    time.sleep(0.5)
                except OSError:
                    break
            else:
                if force or typer.confirm("Worker didn't stop gracefully. Force kill?"):
                    typer.echo(f"Force killing NoETL worker with PID {pid}...")
                    os.kill(pid, signal.SIGKILL)

            if os.path.exists(worker_pid_path):
                os.remove(worker_pid_path)

            typer.echo("NoETL worker stopped successfully.")

        except OSError:
            typer.echo(f"No process found with PID {pid}. The worker may have been stopped already.")
            if os.path.exists(worker_pid_path):
                os.remove(worker_pid_path)

    except Exception as e:
        typer.echo(f"Error stopping NoETL worker service: {e}")
        raise typer.Exit(code=1)

@server_app.command("start")
def start_server(
    init_db: bool = typer.Option(False, "--init-db/--no-init-db", help="Initialize database schema on startup (optional)")
):
    """
    Start the NoETL server using settings loaded from environment.
    All runtime settings (host, port, enable_ui, debug, server runtime, workers, reload) are read from config.
    """
    global _enable_ui

    from noetl.core.config import _settings
    import noetl.core.config as core_config
    core_config._settings = None
    core_config._ENV_LOADED = False
    
    settings = get_settings(reload=True)

    _enable_ui = settings.enable_ui

    log_level = "debug" if settings.debug else "info"
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.DEBUG if settings.debug else logging.INFO
    )

    ui_status = "enabled" if settings.enable_ui else "disabled"
    debug_status = "enabled" if settings.debug else "disabled"
    logger.info(f"Starting NoETL API server at http://{settings.host}:{settings.port} (UI {ui_status}, Debug {debug_status})")


    if init_db:
        logger.info("Initializing NoETL system metadata by request (--init-db).")
        try:
            db_schema = DatabaseSchema(auto_setup=True)

            async def _init_db():
                await db_schema.initialize_connection()
                await db_schema.init_database()

            asyncio.run(_init_db())
            logger.info("NoETL database schema initialized.")
        except Exception as e:
            logger.error(f"FATAL: Error initializing NoETL system metadata: {e}", exc_info=True)
            if os.path.exists(settings.pid_file_path):
                os.remove(settings.pid_file_path)
            legacy_makefile_pid_file = "logs/server.pid"
            if os.path.exists(legacy_makefile_pid_file):
                os.remove(legacy_makefile_pid_file)
            raise typer.Exit(code=1)

    server_runtime = settings.server_runtime
    if server_runtime == "auto":
        try:
            import gunicorn  # type: ignore
            server_type = "gunicorn"
            logger.info("Auto-detected Gunicorn as the server runtime.")
        except ImportError:
            server_type = "uvicorn"
            logger.info("Auto-detected Uvicorn as the server runtime (Gunicorn not available).")
    else:
        server_type = server_runtime
        logger.info(f"Using {server_type} as the server runtime.")

    os.makedirs(settings.pid_file_dir, exist_ok=True)

    if os.path.exists(settings.pid_file_path):
        try:
            with open(settings.pid_file_path, 'r') as pf:
                existing_pid = int(pf.read().strip())
            try:
                os.kill(existing_pid, 0)
                logger.info(f"Server already running with PID {existing_pid} (PID file: {settings.pid_file_path}). Aborting start.")
                raise typer.Exit(code=0)
            except OSError:
                logger.info("Found stale PID file. Removing it before start.")
                os.remove(settings.pid_file_path)
        except Exception:
            try:
                os.remove(settings.pid_file_path)
            except Exception:
                pass

    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        host = str(settings.host)
        port = int(settings.port)
        try:
            if s.connect_ex((host, port)) == 0:
                logger.error(f"Port {host}:{port} is already in use. Aborting start.")
                raise typer.Exit(code=1)
        except socket.gaierror:
            pass

    try:
        workers = int(settings.server_workers)
        reload = bool(settings.server_reload)
        if server_type == "gunicorn":
            _run_with_gunicorn(settings.host, settings.port, workers, reload, log_level)
        else:
            import subprocess, sys
            # Determine access log behavior (default: off to reduce noise for frequent endpoints like /queue/lease)
            access_log_env = os.environ.get("NOETL_ACCESS_LOG", "false").strip().lower()
            access_log = access_log_env in ("1","true","yes","y","on")

            cmd = [
                sys.executable, "-m", "uvicorn",
                "noetl.server:create_app",
                "--factory",
                "--host", str(settings.host),
                "--port", str(settings.port),
                "--log-level", log_level
            ]
            if not access_log:
                cmd.append("--no-access-log")
            if reload:
                cmd.append("--reload")
            if workers and int(workers) > 1:
                cmd.extend(["--workers", str(workers)])
            logger.info(f"Spawning uvicorn subprocess: {' '.join(cmd)}")
            child_env = os.environ.copy()
            required_keys = [
                'POSTGRES_USER','POSTGRES_PASSWORD','POSTGRES_DB','POSTGRES_HOST','POSTGRES_PORT',
                'NOETL_USER','NOETL_PASSWORD','NOETL_SCHEMA','NOETL_HOST','NOETL_PORT',
                'NOETL_ENABLE_UI','NOETL_DEBUG','NOETL_SERVER','NOETL_SERVER_WORKERS','NOETL_SERVER_RELOAD','NOETL_DROP_SCHEMA','NOETL_SCHEMA_VALIDATE'
            ]
            for k in required_keys:
                if k not in child_env and hasattr(settings, k.lower() if k.startswith('NOETL_') or k.startswith('POSTGRES_') else k):
                    child_env[k] = str(getattr(settings, k.lower()))
            proc = subprocess.Popen(cmd, stdout=open('logs/server.out','a'), stderr=open('logs/server.err','a'), env=child_env)
            with open(settings.pid_file_path, 'w') as f:
                f.write(str(proc.pid))
            logger.info(f"Spawned server process PID {proc.pid}")
    except Exception:
        if os.path.exists(settings.pid_file_path):
            try:
                os.remove(settings.pid_file_path)
            except Exception:
                pass
        raise

def _run_with_uvicorn(host: str, port: int, workers: int, reload: bool, log_level: str):
    access_log_env = os.environ.get("NOETL_ACCESS_LOG", "false").strip().lower()
    access_log = access_log_env in ("1","true","yes","y","on")
    uvicorn.run(
        "noetl.server:create_app",
        factory=True,
        host=host,
        port=port,
        workers=workers if workers and workers > 1 else None,
        reload=reload,
        log_level=log_level,
        access_log=access_log,
        lifespan="on",
        timeout_graceful_shutdown=10
    )


def _run_with_gunicorn(host: str, port: int, workers: int, reload: bool, log_level: str):
    try:
        import subprocess
        import sys

        cmd = [
            sys.executable, "-m", "gunicorn",
            "noetl.server:create_app()",
            "--bind", f"{host}:{port}",
            "--workers", str(workers),
            "--worker-class", "uvicorn.workers.UvicornWorker",
            "--log-level", log_level,
            "--graceful-timeout", "5",
            "--timeout", "10",
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
    This command should not require full environment configuration.
    Strategy:
    1) Try PID file if present; stop that process.
    2) If not present or stale, try to detect any process listening on NOETL_PORT (from env or default 8082) and stop it.
    """
    pid_file_path = os.path.expanduser("~/.noetl/noetl_server.pid")

    def _kill_pid(pid: int) -> bool:
        try:
            os.kill(pid, 0)
        except OSError:
            return False
        if not force:
            confirm = typer.confirm(f"Stop NoETL server with PID {pid}?")
            if not confirm:
                typer.echo("Operation cancelled.")
                return False
        typer.echo(f"Stopping NoETL server with PID {pid}...")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        for _ in range(20):
            try:
                os.kill(pid, 0)
                time.sleep(0.5)
            except OSError:
                break
        else:
            if force or typer.confirm("Server didn't stop gracefully. Force kill?"):
                typer.echo(f"Force killing NoETL server with PID {pid}...")
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        return True

    # 1) Try PID file path first
    if os.path.exists(pid_file_path):
        try:
            with open(pid_file_path, 'r') as f:
                pid = int(f.read().strip())
            if _kill_pid(pid):
                if os.path.exists(pid_file_path):
                    os.remove(pid_file_path)
                typer.echo("NoETL server stopped successfully.")
                return
        except Exception:
            # If PID file unreadable, fall through to port-based stop
            pass
        # Stale PID file; remove it before trying port-based stop
        try:
            if os.path.exists(pid_file_path):
                os.remove(pid_file_path)
        except Exception:
            pass

    # 2) Fallback: detect listening process on configured port and stop it
    host = os.environ.get("NOETL_HOST", "localhost")
    try:
        port = int(os.environ.get("NOETL_PORT", 8082))
    except Exception:
        port = 8082

    # Best-effort: parse lsof output (macOS/linux) to get PID listening on port
    try:
        import subprocess, shlex
        cmd = f"lsof -t -i TCP:{port} -sTCP:LISTEN"
        proc = subprocess.run(shlex.split(cmd), capture_output=True, text=True)
        pids = [int(x) for x in proc.stdout.strip().split() if x.strip().isdigit()]
    except Exception:
        pids = []

    if not pids:
        typer.echo("No running NoETL server found.")
        return

    stopped_any = False
    for pid in pids:
        if _kill_pid(pid):
            stopped_any = True
    if stopped_any:
        typer.echo("NoETL server stopped successfully (port-based fallback).")
    else:
        typer.echo("No running NoETL server found.")

@cli_app.command("server", hidden=True)
def run_server():
    """
    Backward-compatible entry; starts server using runtime settings from config.
    """
    start_server()


@db_app.command("apply-schema")
def db_apply_schema(
    schema_file: str = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to schema_ddl.sql (defaults to packaged noetl/database/ddl/postgres/schema_ddl.sql)",
    ),
    ensure_role: bool = typer.Option(
        True,
        "--ensure-role/--no-ensure-role",
        help="Ensure the noetl database role and schema exist before applying DDL"
    ),
):
    """Apply the canonical schema DDL to the configured Postgres database.

    Uses the admin connection string from environment (POSTGRES_* / settings).
    """
    try:
        settings = get_settings(reload=True)
        admin_conn = settings.admin_conn_string
        import psycopg

        # Load DDL from provided path, else from packaged resource
        if schema_file:
            if not os.path.exists(schema_file):
                typer.echo(f"Schema file not found: {schema_file}")
                raise typer.Exit(code=2)
            with open(schema_file, "r", encoding="utf-8") as f:
                ddl_sql = f.read()
            ddl_origin = schema_file
        else:
            try:
                from importlib import resources as pkg_resources
                ddl_sql = pkg_resources.files("noetl").joinpath("database/ddl/postgres/schema_ddl.sql").read_text(encoding="utf-8")
                ddl_origin = "package://noetl/database/ddl/postgres/schema_ddl.sql"
            except Exception as e:
                typer.echo(f"Failed to read packaged schema DDL: {e}")
                raise typer.Exit(code=2)

        with psycopg.connect(admin_conn) as conn:
            conn.execute("SET client_min_messages TO WARNING")
            with conn.cursor() as cur:
                if ensure_role:
                    # Best-effort: ensure role and schema exist
                    try:
                        cur.execute(
                            """
                            DO $$
                            BEGIN
                              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = %s) THEN
                                EXECUTE format('CREATE USER %I LOGIN', %s);
                              END IF;
                            END
                            $$;
                            """,
                            (settings.noetl_user, settings.noetl_user),
                        )
                    except Exception:
                        pass
                # Apply DDL as a single batch
                cur.execute(ddl_sql)
                conn.commit()
        typer.echo(f"Applied schema from {ddl_origin}")
    except Exception as e:
        typer.echo(f"Error applying schema: {e}")
        raise typer.Exit(code=1)


@cli_app.command("catalog")
def manage_catalog(
    action: str = typer.Argument(help="Action to perform: register, execute, list"),
    resource_type_or_path: str = typer.Argument(help="Resource type (for list) or path (for register/execute)"),
    path: str = typer.Argument(None, help="Path to resource file (for register) or resource path (for execute) - optional if type is inferred"),
    version: str = typer.Option(None, "--version", "-v", help="Version of the resource to execute."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str | None = typer.Option(None, "--host", help="NoETL server host for client connections."),
    port: int | None = typer.Option(None, "--port", "-p", help="NoETL server port."),
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
    resource_type: str | None = None
    file_path: str | None = None
    detected_resource_type: str | None = None

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
            resource_type = "playbook"  # Default to playbook for execute
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
            if host is None or port is None:
                logger.error("Error: --host and --port are required for this client command")
                raise typer.Exit(code=1)
            with open(file_path, 'r') as f:
                content = f.read()
            content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            url = f"http://{host}:{port}/api/catalog/register"
            headers = {"Content-Type": "application/json"}
            data = {
                "content_base64": content_base64,
                "resource_type": "Playbook"
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
            logger.info(f"Example: noetl catalog execute playbook weather_example --version 0.1.0")
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

            if host is None or port is None:
                logger.error("Error: --host and --port are required for this client command")
                raise typer.Exit(code=1)
            url = f"http://{host}:{port}/api/run/playbook"
            headers = {"Content-Type": "application/json"}
            data = {
                "path": path,
                "args": input_payload,
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

                execution_id = result.get("execution_id")
                if execution_id:
                    logger.info(f"Execution ID: {execution_id}")
                    
                    # The execution result may be in the 'result' field
                    execution_result = result.get('result', {})
                    if execution_result:
                        logger.debug(f"Full execution result: {json.dumps(execution_result, indent=2, cls=DateTimeEncoder)}")

                    any_errors = any(
                        isinstance(step_result, dict) and step_result.get('status') == 'error'
                        for step_name, step_result in execution_result.items()
                    )

                    logger.info("\n" + "="*80)
                    logger.info("EXECUTION REPORT")
                    logger.info("="*80)
                    logger.info(f"{resource_type.capitalize()} Path: {path}")
                    logger.info(f"Version: {version or 'latest'}")
                    logger.info(f"Execution ID: {result.get('execution_id')}")

                    if any_errors:
                        logger.info(f"Status: FAILED")
                    else:
                        logger.info(f"Status: SUCCESS")

                    logger.info("-"*80)

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
                                    logger.info(f"{step_name}: SUCCESS ({len(command_details)} commands)")
                                else:
                                    logger.info(f"{step_name}: SUCCESS")
                            elif status == 'error':
                                error_count += 1
                                error_details = []
                                for key, value in step_result.items():
                                    if key.startswith('command_') and isinstance(value, dict):
                                        if value.get('status') == 'error':
                                            error_msg = value.get('message', 'Unknown error')
                                            error_details.append(f"{key}: {error_msg}")

                                if error_details:
                                    logger.info(f"{step_name}: ERROR - {'; '.join(error_details)}")
                                else:
                                    error_msg = step_result.get('error', 'Unknown error')
                                    logger.info(f"{step_name}: ERROR - {error_msg}")
                            elif status == 'skipped':
                                skipped_count += 1
                                logger.info(f"{step_name}: SKIPPED")
                            elif status == 'partial':
                                success_count += 1
                                logger.info(f"{step_name}: PARTIAL SUCCESS")
                            else:
                                success_count += 1
                                logger.info(f"{step_name}: COMPLETED with unclear status")
                        else:
                            success_count += 1
                            logger.info(f"{step_name}: SUCCESS")

                    logger.info("-"*80)
                    logger.info(f"Total Steps: {step_count}")
                    logger.info(f"Successful: {success_count}")
                    logger.info(f"Failed: {error_count}")
                    logger.info(f"Skipped: {skipped_count}")
                    logger.info("="*80)
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
                    logger.info(f"No {resource_type}s found in catalog.")
                    return

                logger.info(f"\n{resource_type.upper()}S IN CATALOG:")
                logger.info("="*80)
                logger.info(f"{'PATH':<40} {'VERSION':<10} {'TYPE':<15} {'TIMESTAMP':<15}")
                logger.info("-"*80)

                for entry in entries:
                    path = entry.get('resource_path', 'Unknown')
                    version = entry.get('resource_version', 'Unknown')
                    res_type = entry.get('resource_type', 'Unknown')
                    timestamp = entry.get('timestamp', 'Unknown')
                    if isinstance(timestamp, str) and 'T' in timestamp:
                        timestamp = timestamp.split('T')[0]
                    logger.info(f"{path:<40} {version:<10} {res_type:<15} {timestamp:<15}")
                logger.info("="*80)
                logger.info(f"Total: {len(entries)} {resource_type}(s)")

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

@cli_app.command("run")
def run_playbook(
    playbook_id: str = typer.Argument(..., help="Playbook path/name as registered in catalog (e.g., examples/weather_loop_example)"),
    host: str = typer.Option("localhost", "--host", help="NoETL server host"),
    port: int = typer.Option(8082, "--port", "-p", help="NoETL server port"),
    input: str = typer.Option(None, "--input", "-i", help="Path to JSON file with parameters"),
    payload: str = typer.Option(None, "--payload", help="Inline JSON string with parameters"),
    merge: bool = typer.Option(False, "--merge", help="Merge parameters into playbook workload on server"),
    json_only: bool = typer.Option(False, "--json", "-j", help="Emit the JSON response"),
):
    """
    Execute a registered playbook by name against a running NoETL server.
    This is an alias for 'noetl execute playbook'.

    Equivalent REST call:
      curl -X POST http://{host}:{port}/api/run/playbook \
           -H "Content-Type: application/json" \
           -d '{"path": "<playbook_path>", "args": {...}}'

    Example:
      noetl run "examples/weather_loop_example" --host localhost --port 8082
    """
    try:
        parameters = {}
        if input:
            try:
                with open(input, "r") as f:
                    parameters = json.load(f)
                typer.echo(f"Loaded parameters from {input}")
            except Exception as e:
                typer.echo(f"Failed to read parameters file: {e}")
                raise typer.Exit(code=1)
        elif payload:
            try:
                parameters = json.loads(payload)
                typer.echo("Parsed parameters from --payload")
            except Exception as e:
                typer.echo(f"Failed to parse --payload JSON: {e}")
                raise typer.Exit(code=1)

        url = f"http://{host}:{port}/api/run/playbook"
        body = {"path": playbook_id, "args": parameters, "merge": merge}
        if not json_only:
            typer.echo(f"POST {url}")
        resp = requests.post(url, json=body)
        if resp.status_code >= 200 and resp.status_code < 300:
            data = resp.json()
            exec_id = data.get("id") or data.get("execution_id")
            if not json_only:
                typer.echo("Execution started")
                if exec_id:
                    typer.echo(f"execution_id: {exec_id}")
            typer.echo(json.dumps(data, indent=2, cls=DateTimeEncoder))
        else:
            if not json_only:
                typer.echo(f"Server returned {resp.status_code}")
                typer.echo(resp.text)
            raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


execute_app = typer.Typer()
cli_app.add_typer(execute_app, name="execute")

@cli_app.command("plan")
def plan_schedule(
    path: str = typer.Argument(..., help="Path to playbook YAML file"),
    resources: str = typer.Option("http_pool=4,pg_pool=5,duckdb_host=1", "--resources", help="Resource capacities as k=v comma list"),
    max_solve_seconds: float = typer.Option(5.0, "--max-solve-seconds", help="Solver time limit in seconds"),
    json_only: bool = typer.Option(True, "--json", "-j", help="Emit only JSON result"),
):
    """
    Build a CP-SAT schedule for a playbook and print JSON.
    """
    try:
        from noetl.core.common import ordered_yaml_load
        from noetl.scheduler import build_plan, CpSatScheduler
        with open(path, "r", encoding="utf-8") as f:
            playbook = ordered_yaml_load(f)
        cap_dict = {}
        if resources:
            for kv in resources.split(","):
                if not kv.strip():
                    continue
                k, v = kv.split("=")
                cap_dict[k.strip()] = int(v)
        steps, edges, caps = build_plan(playbook, cap_dict)
        sched = CpSatScheduler(max_seconds=max_solve_seconds).solve(steps, edges, caps)
        out = {
            "steps": [s.__dict__ for s in steps],
            "edges": [e.__dict__ for e in edges],
            "capacities": [{"name": c.name, "capacity": c.capacity} for c in caps],
            "schedule": {
                "starts_ms": sched.starts_ms,
                "ends_ms": sched.ends_ms,
                "durations_ms": sched.durations_ms,
                "makespan_ms": max(sched.ends_ms.values()) if sched.ends_ms else 0,
            },
        }
        typer.echo(json.dumps(out, indent=2 if not json_only else None))
    except Exception as e:
        typer.echo(f"Error building plan: {e}")
        raise typer.Exit(code=1)


@execute_app.command("playbook")
def execute_playbook_by_name(
    playbook_id: str = typer.Argument(..., help="Playbook path/name as registered in catalog (e.g., examples/weather_loop_example)"),
    host: str = typer.Option("localhost", "--host", help="NoETL server host"),
    port: int = typer.Option(8082, "--port", "-p", help="NoETL server port"),
    input: str = typer.Option(None, "--input", "-i", help="Path to JSON file with parameters"),
    payload: str = typer.Option(None, "--payload", help="Inline JSON string with parameters"),
    merge: bool = typer.Option(False, "--merge", help="Merge parameters into playbook workload on server"),
    json_only: bool = typer.Option(False, "--json", "-j", help="Emit the JSON response"),
):
    """
    Execute a registered playbook by name against a running NoETL server.

    Equivalent REST call:
      curl -X POST http://{host}:{port}/api/run/playbook \
           -H "Content-Type: application/json" \
           -d '{"path": "<playbook_path>", "args": {...}}'

    Example:
      noetl execute playbook "examples/weather_loop_example" --host localhost --port 8082
    """
    try:
        parameters = {}
        if input:
            try:
                with open(input, "r") as f:
                    parameters = json.load(f)
                typer.echo(f"Loaded parameters from {input}")
            except Exception as e:
                typer.echo(f"Failed to read parameters file: {e}")
                raise typer.Exit(code=1)
        elif payload:
            try:
                parameters = json.loads(payload)
                typer.echo("Parsed parameters from --payload")
            except Exception as e:
                typer.echo(f"Failed to parse --payload JSON: {e}")
                raise typer.Exit(code=1)

        url = f"http://{host}:{port}/api/run/playbook"
        logger.info(f"POST {url}")
        body = {"path": playbook_id, "args": parameters, "merge": merge}
        if not json_only:
            typer.echo(f"POST {url}")
        resp = requests.post(url, json=body)
        if resp.status_code >= 200 and resp.status_code < 300:
            data = resp.json()
            exec_id = data.get("id") or data.get("execution_id")
            if not json_only:
                typer.echo("Execution started")
                if exec_id:
                    typer.echo(f"execution_id: {exec_id}")
            typer.echo(json.dumps(data, indent=2, cls=DateTimeEncoder))
        else:
            if not json_only:
                typer.echo(f"Server returned {resp.status_code}")
                typer.echo(resp.text)
            raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


@execute_app.command("status")
def execution_status(
    execution_id: str = typer.Argument(..., help="Execution ID to query"),
    host: str = typer.Option("localhost", "--host", help="NoETL server host"),
    port: int = typer.Option(8082, "--port", "-p", help="NoETL server port"),
    json_only: bool = typer.Option(False, "--json", "-j", help="Emit only the JSON response (no preamble lines)"),
):
    """
    Fetch execution status and details from the server.

    Equivalent REST call:
      curl -X GET http://{host}:{port}/api/executions/{execution_id}

    Example:
      noetl execute status 219728589581451264
    """
    try:
        url = f"http://{host}:{port}/api/executions/{execution_id}"
        if not json_only:
            typer.echo(f"GET {url}")
        resp = requests.get(url)
        if resp.status_code == 200:
            typer.echo(json.dumps(resp.json(), indent=2, cls=DateTimeEncoder))
        else:
            if not json_only:
                typer.echo(f"Server returned {resp.status_code}")
                typer.echo(resp.text)
            raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"Error: {e}")
        raise typer.Exit(code=1)


@cli_app.command("register")
def register_playbook(
    playbook_file: str = typer.Argument(help="Path to playbook file to register"),
    host: str | None = typer.Option(None, "--host", help="NoETL server host for client connections."),
    port: int | None = typer.Option(None, "--port", "-p", help="NoETL server port.")
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
        if host is None or port is None:
            typer.echo("Error: --host and --port are required for this client command")
            raise typer.Exit(code=1)
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
            logger.info(f"Resource path: {result.get('path')}")
            logger.info(f"Resource version: {result.get('version')}")
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
