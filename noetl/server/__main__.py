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
