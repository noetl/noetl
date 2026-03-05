"""
NoETL Server Entry Point

This module provides a command-line entry point for starting the NoETL server.
It's designed to be called from the Rust CLI or run directly.

Usage:
    python -m noetl.server
    python -m noetl.server --host 0.0.0.0 --port 8082
    python -m noetl.server --init-db
"""

import argparse
import sys
import asyncio
import logging
import os

_DEFAULT_SUPPRESSED_ACCESS_PATHS = (
    "/api/worker/pool/register",
    "/api/health",
    "/health",
    "/api/pool/status",
    "/metrics",
)


def _load_suppressed_access_paths() -> tuple[str, ...]:
    """
    Resolve access-log suppression list.

    NOETL_ACCESS_LOG_SUPPRESS_PATHS supports comma-separated path fragments.
    Empty value falls back to defaults.
    """
    raw = os.getenv("NOETL_ACCESS_LOG_SUPPRESS_PATHS", "").strip()
    if not raw:
        return _DEFAULT_SUPPRESSED_ACCESS_PATHS
    parts = tuple(p.strip() for p in raw.split(",") if p.strip())
    return parts or _DEFAULT_SUPPRESSED_ACCESS_PATHS


class AccessLogFilter(logging.Filter):
    """Filter noisy health/internal access logs to prevent log floods."""

    def __init__(self, suppressed_paths: tuple[str, ...]):
        super().__init__()
        self._suppressed_paths = tuple(p.lower() for p in suppressed_paths if p)

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage().lower()
        for path in self._suppressed_paths:
            if path in message:
                return False
        return True


def main():
    """Entry point for NoETL server."""
    parser = argparse.ArgumentParser(description="NoETL Server")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Server host (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8082,
        help="Server port (default: 8082)"
    )
    parser.add_argument(
        "--init-db",
        action="store_true",
        help="Initialize database schema before starting"
    )
    
    args = parser.parse_args()
    
    if args.init_db:
        print("Initializing database schema...")
        from noetl.database.manager import initialize_db
        try:
            asyncio.run(initialize_db())
            print("Database initialized successfully")
        except Exception as e:
            print(f"Database initialization failed: {e}", file=sys.stderr)
            sys.exit(1)
    
    print(f"Starting NoETL server on {args.host}:{args.port}...")
    
    try:
        import uvicorn
        from noetl.server.app import create_app

        logging.getLogger("uvicorn.access").addFilter(
            AccessLogFilter(_load_suppressed_access_paths())
        )
        
        app = create_app()
        uvicorn.run(app, host=args.host, port=args.port)
    except KeyboardInterrupt:
        print("\nServer stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Server failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
