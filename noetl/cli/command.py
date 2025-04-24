import typer
from pathlib import Path
import base64
from noetl.shared.connectors.requestify import RequestHandler
from noetl.config.config import CloudConfig
import asyncio
from noetl.shared import setup_logger

logger = setup_logger(__name__, include_location=True)
cli = typer.Typer(no_args_is_help=True)
catalog_cli = typer.Typer()

@catalog_cli.command("register")
def register(
    file_path: Path = typer.Argument(..., exists=True, help="Path to the YAML file to register."),
    host: str = typer.Option("0.0.0.0", help="API host"),
    port: int = typer.Option(8082, help="API port"),
):
    try:
        file_contents = file_path.read_bytes()
        encoded_yaml = base64.b64encode(file_contents).decode("utf-8")
        url = f"http://{host}:{port}/catalog/register"
        handler = RequestHandler(CloudConfig())
        result = asyncio.run(handler.request(
            url=url,
            method="POST",
            json_data={"content_base64": encoded_yaml}
        ))
        # logger.debug(f"Register result: {result}")
        status_code = result.get("status_code")
        if status_code and 200 <= status_code < 300:
            status = result.get("body").get("status")
            message = result.get("body").get("message")
            typer.echo({"status_code": status_code, "status": status, "message": message})
        else:
            typer.echo({"status": "error", "details": result}, err=True)
            raise typer.Exit(code=1)

    except Exception as e:
        typer.echo({"status": "error", "details": str(e)}, err=True)
        raise typer.Exit(code=1)

cli.add_typer(catalog_cli, name="catalog")


@cli.command("health")
def health_check(
    host: str = typer.Option("0.0.0.0", help="API host check."),
    port: int = typer.Option(8082, help="API port check."),
):
    try:
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
    except Exception as e:
        typer.echo(f"Error during health check: {str(e)}", err=True)
        raise typer.Exit(code=1)

cli.add_typer(catalog_cli, name="catalog")

if __name__ == "__main__":
    cli()