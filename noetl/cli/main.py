"""
CLI entrypoint wrapper; forwards to legacy commands for now.
"""

from noetl.cli.noetl_ctl import cli_app as app  # type: ignore


def main() -> None:
    app()

