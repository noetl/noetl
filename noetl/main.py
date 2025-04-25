from noetl.shared import setup_logger
from noetl.server.app import create_app
from noetl.cli.command import cli
import uvicorn
import typer

logger = setup_logger(__name__, include_location=True)

@cli.command("server")
def create_server(
    host: str = typer.Option("0.0.0.0", help="Server host."),
    port: int = typer.Option(8082, help="Server port."),
    reload: bool = typer.Option(False, help="Server auto-reload (development).")
):
    app = create_app()
    uvicorn.run(app, host=host, port=port, reload=reload)

def main():
    cli()

if __name__ == "__main__":
    main()
