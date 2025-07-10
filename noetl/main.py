import uvicorn
import typer
import os
import json
import logging
import base64
import requests
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, FileResponse
from noetl.server import router as server_router
from noetl.common import deep_merge, setup_logger
from noetl.worker import NoETLAgent
from noetl.schema import DatabaseSchema

# Setup logger for the main module
logger = setup_logger(__name__, include_location=True)

# Use a distinct name for the Typer CLI application to avoid confusion with the FastAPI app.
cli_app = typer.Typer()


def create_app() -> FastAPI:
    """
    Creates and configures the main FastAPI application instance.
    This function is the factory for Uvicorn.
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

    # --- Database Initialization ---
    try:
        logger.info("Initializing NoETL system metadata.")
        db_schema = DatabaseSchema(auto_setup=False)
        db_schema.create_noetl_metadata()
        db_schema.init_database()
        logger.info("NoETL user and database schema initialized.")
    except Exception as e:
        logger.error(f"Error initializing NoETL system metadata: {e}", exc_info=True)
        logger.warning("Continuing with server startup despite database initialization error.")

    # --- UI Serving Setup ---
    package_dir = Path(__file__).parent
    ui_path = package_dir / "ui"
    templates_path = ui_path / "templates"
    static_path = ui_path / "static"
    assets_path = static_path / "assets"

    templates = None
    if templates_path.exists() and assets_path.exists():
        templates = Jinja2Templates(directory=templates_path)

        # Mount the /assets directory to serve JS, CSS, etc.
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")
        logger.info(f"UI assets mounted from: {assets_path}")

        # Add a specific route for the favicon
        @app.get("/favicon.svg", include_in_schema=False)
        async def favicon():
            favicon_file = static_path / "favicon.svg"
            if favicon_file.exists():
                return FileResponse(favicon_file)
            return HTMLResponse(status_code=404)
    else:
        logger.warning(f"UI files not found. Searched in: {ui_path}")

    # --- API Router ---
    app.include_router(server_router)

    # --- Health Check ---
    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    # --- SPA Catch-all Route ---
    # This single route handles serving all your HTML pages.
    # It must be defined *after* all other API routes.
    if templates:
        @app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
        async def serve_spa(request: Request, full_path: str):
            """Serves the appropriate HTML template for any given path."""
            if full_path.startswith("editor") or full_path.startswith("playbook"):
                template_name = "editor.html"
            elif full_path.startswith("execution"):
                template_name = "execution.html"
            elif full_path.startswith("catalog"):
                template_name = "catalog.html"
            else:
                template_name = "index.html"  # Default/fallback

            return templates.TemplateResponse(template_name, {"request": request})
    else:
        @app.get("/", response_class=HTMLResponse, include_in_schema=False)
        async def root_no_ui():
            return {"message": "NoETL API is running, but UI is not available"}

    return app


# --- Typer CLI Commands ---

@cli_app.command("server")
def run_server(
    host: str = typer.Option("0.0.0.0", help="Server host."),
    port: int = typer.Option(8080, help="Server port."),
    reload: bool = typer.Option(False, help="Server auto-reload.")
):
    """Starts the NoETL web server."""
    logger.info(f"Starting NoETL API server at http://{host}:{port}")
    # Use the factory pattern for Uvicorn, which is best practice.
    uvicorn.run("noetl.main:create_app", factory=True, host=host, port=port, reload=reload)


@cli_app.command("agent")
def run_agent(
    file: str = typer.Option(..., "--file", "-f", help="Path to playbook YAML file."),
    mock: bool = typer.Option(False, help="Run in mock mode"),
    output: str = typer.Option("json", "--output", "-o", help="Output format, json or plain."),
    export: str = typer.Option(None, help="Export execution data to Parquet file."),
    mlflow: bool = typer.Option(False, help="Use ML model for workflow control."),
    postgres: str = typer.Option(None, help="Postgres connection string."),
    duckdb: str = typer.Option(None, help="Path to DuckDB file for business logic in playbooks."),
    input: str = typer.Option(None, help="Path to the input payload JSON file for the playbook."),
    payload: str = typer.Option(None, help="JSON input payload string for the playbook."),
    merge: bool = typer.Option(False, help="Merge the input payload with the workload section."),
    debug: bool = typer.Option(False, help="Debug logging mode.")
):
    """Executes a NoETL playbook as a local agent."""
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

        agent = NoETLAgent(file, mock_mode=mock, pgdb=pgdb_conn)
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
            logger.info("Using default workload from playbook.")
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
        logger.error(f"Error executing playbook: {e}", exc_info=True)
        print(f"Error executing playbook: {e}")
        raise typer.Exit(code=1)


@cli_app.command("playbook")
def manage_playbook(
    register: str = typer.Option(None, "--register", "-r", help="Path to playbook file to register."),
    execute: bool = typer.Option(False, "--execute", "-e", help="Execute a playbook by path."),
    path: str = typer.Option(None, "--path", help="Path of the playbook to execute."),
    version: str = typer.Option(None, "--version", "-v", help="Version of the playbook to execute."),
    input: str = typer.Option(None, "--input", "-i", help="Path to payload file."),
    payload: str = typer.Option(None, "--payload", help="Payload string."),
    host: str = typer.Option("localhost", "--host", help="NoETL server host for client connections."),
    port: int = typer.Option(8082, "--port", "-p", help="NoETL server port."),
    sync: bool = typer.Option(True, "--sync", help="Sync up execution data to Postgres."),
    merge: bool = typer.Option(False, "--merge", help="Merge the input payload with the workload section of playbook.")
):
    """Registers or executes a playbook via the NoETL server."""
    if register:
        try:
            if not os.path.exists(register):
                logger.error(f"File not found: {register}")
                raise typer.Exit(code=1)
            with open(register, 'r') as f:
                content = f.read()
            content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            url = f"http://{host}:{port}/catalog/register"
            headers = {"Content-Type": "application/json"}
            data = {"content_base64": content_base64}
            logger.info(f"Registering playbook {register} with NoETL server at {url}")
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
    elif execute:
        try:
            if not path:
                logger.error("Path is required when using --execute")
                logger.info("Example: noetl playbook --execute --path weather_example --version 0.1.0")
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

            url = f"http://{host}:{port}/agent/execute"
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
                logger.info(f"Executing playbook {path} version {version} on NoETL server at {url}")
            else:
                logger.info(f"Executing playbook {path} (latest version) on NoETL server at {url}")
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
                logger.error(f"Failed to execute playbook: {response.status_code}.")
                logger.error(f"Response: {response.text}.")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error executing playbook: {e}.")
            raise typer.Exit(code=1)
    else:
        logger.info("No action specified. Use --register to register a playbook or --execute to execute a playbook.")
        logger.info("Examples:")
        logger.info("  noetl playbook --register ./playbook/weather_example.yaml")
        logger.info("  noetl playbook --execute --path weather_example --version 0.1.0 --payload '{\"city\": \"New York\"}'")
        logger.info("  noetl playbook --execute --path weather_example --input ./data/input/payload.json")


def main():
    """Main entry point for the CLI application."""
    cli_app()


# Create the app instance for external imports (e.g., from entry points)
app = create_app()


if __name__ == "__main__":
    main()
