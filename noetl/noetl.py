from noetl.shared import setup_logger
from noetl.server.app import create_app
from noetl.shared.connectors.requestify import RequestHandler
from noetl.config.config import CloudConfig
from pathlib import Path
import asyncio
import uvicorn
import yaml
import typer

logger = setup_logger(__name__, include_location=True)

cli = typer.Typer(no_args_is_help=True)
@cli.command("server")
def serve(
    host: str = typer.Option("0.0.0.0", help="Server host."),
    port: int = typer.Option(8082, help="Server port."),
    reload: bool = typer.Option(False, help="Server auto-reload (development).")
):
    app = create_app()
    uvicorn.run(app, host=host, port=port, reload=reload)

@cli.command()
def health(
    host: str = typer.Option("0.0.0.0", help="API host check."),
    port: int = typer.Option(8082, help="API port check.")
):
    url = f"http://{host}:{port}/health"
    handler = RequestHandler(CloudConfig())
    result = asyncio.run(handler.request(
        url=url,
        method="GET"
    ))
    status = result.get("status_code")
    if status and 200 <= status < 300:
        typer.echo(result.get("body"))
    else:
        typer.echo(f"Health check failed: {result}.", err=True)
        raise typer.Exit(code=1)

@cli.command("register-playbook")
def register_playbook(
    path: Path = typer.Argument(..., exists=True, help="Path to the playbook YAML file."),
    host: str = typer.Option("0.0.0.0", help="API host"),
    port: int = typer.Option(8082, help="API port")
):
    payload = yaml.safe_load(path.read_text())
    url = f"http://{host}:{port}/api/playbooks"
    handler = RequestHandler(CloudConfig())
    result = asyncio.run(handler.request(
        url=url,
        method="POST",
        json_data=payload
    ))
    status = result.get("status_code")
    if status and 200 <= status < 300:
        typer.echo(f"Playbook registered: {result.get('body')}")
    else:
        typer.echo(f"Registration failed: {result}", err=True)
        raise typer.Exit(code=1)

@cli.command("run-worker")
def run_worker(
    name: str = typer.Argument(..., help="Name of the worker to run.")
):
    # from noetl.worker import run_worker as run_worker
    # run_worker(name)
    pass


def main():
    cli()

if __name__ == "__main__":
    main()
