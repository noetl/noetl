import uvicorn
import typer
import os
import json
import logging
import base64
import requests
from pathlib import Path
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from noetl.server import router as server_router
from noetl.system import router as system_router
from noetl.common import deep_merge, setup_logger
from noetl.worker import Worker
from noetl.schema import DatabaseSchema

logger = setup_logger(__name__, include_location=True)

cli_app = typer.Typer()


_enable_ui = True

def create_app() -> FastAPI:
    """
    This function is the factory for Uvicorn.
    """
    global _enable_ui

    return _create_app(_enable_ui)

def _create_app(enable_ui: bool = True) -> FastAPI:
    """
    Creates the main FastAPI application instance.

    Args:
        enable_ui: Whether to enable UI components (default: True)
    """
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
        logger.warning("Continuing with server startup despite database initialization error.")

    package_dir = Path(__file__).parent
    ui_build_path = package_dir / "ui" / "build"

    app.include_router(server_router, prefix="/api")
    app.include_router(system_router, prefix="/api/sys", tags=["System"])

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    if enable_ui and ui_build_path.exists():
        # Serve specific files first
        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            favicon_file = ui_build_path / "favicon.ico"
            if favicon_file.exists():
                return FileResponse(favicon_file)
            return FileResponse(ui_build_path / "index.html")
        
        # Mount static files for assets
        app.mount("/assets", StaticFiles(directory=ui_build_path / "assets"), name="assets")
        
        # Catch-all route for SPA routing - this handles all other routes
        @app.get("/{catchall:path}", include_in_schema=False)
        async def spa_catchall(catchall: str):
            return FileResponse(ui_build_path / "index.html")
        
        # Root route
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
    no_ui: bool = typer.Option(False, "--no-ui", help="Disable the UI components.")
):
    global _enable_ui

    if not no_ui and os.environ.get("NOETL_ENABLE_UI", "true").lower() == "false":
        no_ui = True

    _enable_ui = not no_ui

    ui_status = "disabled" if no_ui else "enabled"
    logger.info(f"Starting NoETL API server at http://{host}:{port} (UI {ui_status})")
    uvicorn.run("noetl.main:create_app", factory=True, host=host, port=port, reload=reload)


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
    debug: bool = typer.Option(False, help="Debug logging mode.")
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
            pgdb_conn = f"dbname={os.environ.get('POSTGRES_DB', 'demo_noetl')} user={os.environ.get('POSTGRES_USER', 'demo')} password={os.environ.get('POSTGRES_PASSWORD', 'demo')} host={os.environ.get('POSTGRES_HOST', 'localhost')} port={os.environ.get('POSTGRES_PORT', '5434')}"
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


@cli_app.command("playbooks")
def manage_playbook(
    register: str = typer.Option(None, "--register", "-r", help="Path to playbooks file to register."),
    execute: bool = typer.Option(False, "--execute", "-e", help="Execute a playbooks by path."),
    path: str = typer.Option(None, "--path", help="Path of the playbooks to execute."),
    version: str = typer.Option(None, "--version", "-v", help="Version of the playbooks to execute."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str = typer.Option("localhost", "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(8082, "--port", "-p", help="NoETL server port."),
    sync: bool = typer.Option(True, "--sync", help="Sync up execution data to Postgres."),
    merge: bool = typer.Option(False, "--merge", help="Merge the input payload with the workload section of playbooks.")
):
    if register:
        try:
            if not os.path.exists(register):
                logger.error(f"File not found: {register}")
                raise typer.Exit(code=1)
            with open(register, 'r') as f:
                content = f.read()
            content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            url = f"http://{host}:{port}/api/catalog/register"
            headers = {"Content-Type": "application/json"}
            data = {"content_base64": content_base64}
            logger.info(f"Registering playbooks {register} with NoETL server at {url}")
            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Playbook registered successfully: {result}")
                logger.info(f"Resource path: {result.get('resource_path')}")
                logger.info(f"Resource version: {result.get('resource_version')}")
            else:
                logger.error(f"Failed to register playbooks: {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error registering playbooks: {e}")
            raise typer.Exit(code=1)
    elif execute:
        try:
            if not path:
                logger.error("Path is required when using --execute")
                logger.info("Example: noetl playbooks --execute --path weather_example --version 0.1.0")
                raise typer.Exit(code=1)

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
                logger.info(f"Executing playbooks {path} version {version} on NoETL server at {url}")
            else:
                logger.info(f"Executing playbooks {path} (latest version) on NoETL server at {url}")
            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Playbook executed.")

                if result.get("status") == "success":
                    logger.info(f"Execution ID: {result.get('execution_id')}")
                    logger.info(f"Result: {json.dumps(result.get('result'), indent=2)}")
                else:
                    logger.error(f"Execution failed: {result.get('error')}.")
                    raise typer.Exit(code=1)
            else:
                logger.error(f"Failed to execute playbooks: {response.status_code}.")
                logger.error(f"Response: {response.text}.")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error executing playbooks: {e}.")
            raise typer.Exit(code=1)
    else:
        logger.info("No action specified. Use --register to register a playbooks or --execute to execute a playbooks.")
        logger.info("Examples:")
        logger.info("  noetl playbooks --register ./playbooks/weather_loop_example.yaml")
        logger.info("  noetl playbooks --execute --path weather_example --version 0.1.0 --payload '{\"city\": \"New York\"}'")
        logger.info("  noetl playbooks --execute --path weather_example --input ./data/input/payload.json")


def main():
    cli_app()
app = create_app()

if __name__ == "__main__":
    main()
