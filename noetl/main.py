import uvicorn
import typer
import os
import json
import logging
import base64
import requests
import importlib.resources
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from noetl.server import router as server_router
from noetl.common import deep_merge
from noetl.worker import NoETLAgent
from noetl.schema import DatabaseSchema
import pathlib
from noetl.common import setup_logger
logger = setup_logger(__name__, include_location=True)

app = typer.Typer()

@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    host: str = typer.Option(None, help="Server host."),
    port: int = typer.Option(None, help="Server port."),
    reload: bool = typer.Option(None, help="Server auto-reload."),
 ):
    if ctx.invoked_subcommand is None and (host is not None or port is not None or reload is not None):
        host = host or "0.0.0.0"
        port = port or 8082
        reload = reload or False
        create_server(host=host, port=port, reload=reload)


def create_app(host: str = "0.0.0.0", port: int = 8082) -> FastAPI:
    try:
        logger.info("Initializing NoETL system metadata.")
        db_schema = DatabaseSchema(auto_setup=False)
        db_schema.create_noetl_metadata()
        db_schema.init_database()
        logger.info("NoETL user and database schema initialized.")
    except Exception as e:
        logger.error(f"Error initializing NoETL system metadata: {e}", exc_info=True)
        logger.warning("Continuing with server startup despite database initialization error.")

    app = FastAPI(
        title="NoETL API",
        description="NoETL API server",
        version="0.1.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    try:
        templates_path = str(importlib.resources.files('ui') / 'templates')
        static_path = str(importlib.resources.files('ui') / 'static')
        logger.info(f"Using UI files from installed package: templates={templates_path}, static={static_path}")
    except (ModuleNotFoundError, ImportError, ValueError) as e:
        logger.warning(f"Could not find UI files in installed package: {e}")
        project_root = pathlib.Path(__file__).parent.parent.absolute()
        templates_path = str(project_root / "ui" / "templates")
        static_path = str(project_root / "ui" / "static")
        logger.info(f"Using UI files from local development path: templates={templates_path}, static={static_path}")

    templates = Jinja2Templates(directory=templates_path)

    class NoCacheStaticFiles(StaticFiles):
        async def __call__(self, scope, receive, send):
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    headers = dict(message.get("headers", []))
                    headers[b"Cache-Control"] = b"no-cache, no-store, must-revalidate"
                    headers[b"Pragma"] = b"no-cache"
                    headers[b"Expires"] = b"0"
                    message["headers"] = [(k, v) for k, v in headers.items()]
                await send(message)

            return await super().__call__(scope, receive, send_wrapper)

    app.mount("/static", NoCacheStaticFiles(directory=static_path), name="static")
    app.include_router(server_router)

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request):
        return templates.TemplateResponse("index.html", {"request": request})

    @app.get("/editor", response_class=HTMLResponse)
    async def editor(request: Request):
        return templates.TemplateResponse("editor.html", {"request": request})

    @app.get("/editor/{path:path}", response_class=HTMLResponse)
    async def editor_with_path(request: Request, path: str):
        return templates.TemplateResponse("editor.html", {"request": request})

    @app.get("/editor/{path:path}/{version}", response_class=HTMLResponse)
    async def editor_with_path_version(request: Request, path: str, version: str):
        return templates.TemplateResponse("editor.html", {"request": request})

    @app.get("/playbook/{path:path}", response_class=HTMLResponse)
    async def playbook_with_path(request: Request, path: str):
        return templates.TemplateResponse("editor.html", {"request": request})

    @app.get("/playbook/{path:path}/{version}", response_class=HTMLResponse)
    async def playbook_with_path_version(request: Request, path: str, version: str):
        return templates.TemplateResponse("editor.html", {"request": request})

    @app.get("/execution/{execution_id}", response_class=HTMLResponse)
    async def execution(request: Request, execution_id: str):
        return templates.TemplateResponse("execution.html", {"request": request})

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app

@app.command("server")
def create_server(
    host: str = typer.Option("0.0.0.0", help="Server host."),
    port: int = typer.Option(8082, help="Server port."),
    reload: bool = typer.Option(False, help="Server auto-reload.")
):
    app = create_app(host=host, port=port)
    logger.info(f"Starting NoETL API server at http://{host}:{port}")
    logger.info(f"Access the server at http://localhost:{port} or http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=reload)

@app.command("agent")
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

@app.command("playbook")
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
        logger.info("  noetl playbook --register ./catalog/playbooks/weather_example.yaml")
        logger.info("  noetl playbook --execute --path weather_example --version 0.1.0 --payload '{\"city\": \"New York\"}'")
        logger.info("  noetl playbook --execute --path weather_example --input ./data/input/payload.json")

def main():
    app()

if __name__ == "__main__":
    app()
