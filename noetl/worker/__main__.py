"""
NoETL Worker Entry Point

This module provides a command-line entry point for starting NoETL workers.
It's designed to be called from the Rust CLI or run directly.

Usage:
    python -m noetl.worker
    python -m noetl.worker --nats-url nats://localhost:4222 --server-url http://localhost:8082
"""

import argparse
import sys
from noetl.worker.v2_worker_nats import run_worker_v2_sync


def main():
    """Entry point for NoETL worker."""
    parser = argparse.ArgumentParser(description="NoETL V2 Worker")
    parser.add_argument(
        "--nats-url",
        default="nats://noetl:noetl@nats.nats.svc.cluster.local:4222",
        help="NATS server URL (default: cluster service URL)"
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="NoETL server URL (default: from environment or cluster service URL)"
    )
    
    args = parser.parse_args()
    
    try:
        run_worker_v2_sync(nats_url=args.nats_url, server_url=args.server_url)
    except KeyboardInterrupt:
        print("\nWorker interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"Worker failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
