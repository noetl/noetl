"""Command-line entrypoint for the NoETL projector worker."""

from __future__ import annotations

import argparse
import sys

from noetl.core.projector.nats_worker import (
    ProjectorWorkerSettings,
    run_projector_worker_sync,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="NoETL projector worker")
    parser.add_argument("--nats-url", default=None, help="NATS server URL")
    parser.add_argument("--stream", default=None, help="JetStream stream name")
    parser.add_argument("--subject", default=None, help="JetStream subject filter")
    parser.add_argument("--consumer", default=None, help="Durable consumer name")
    parser.add_argument("--shard-id", default=None, help="Stable projector shard id")
    parser.add_argument("--shard-count", type=int, default=None, help="Total projector shard count")
    args = parser.parse_args()

    try:
        from noetl.core.projector.nats_worker import load_projector_worker_settings

        base = load_projector_worker_settings()
        settings = ProjectorWorkerSettings(
            nats_url=args.nats_url or base.nats_url,
            stream_name=args.stream or base.stream_name,
            subject=args.subject or base.subject,
            consumer_name=args.consumer or base.consumer_name,
            shard_id=args.shard_id or base.shard_id,
            shard_count=max(1, args.shard_count or base.shard_count),
            max_inflight=base.max_inflight,
            max_ack_pending=base.max_ack_pending,
            fetch_timeout_seconds=base.fetch_timeout_seconds,
            fetch_heartbeat_seconds=base.fetch_heartbeat_seconds,
        )
        run_projector_worker_sync(settings=settings)
    except KeyboardInterrupt:
        print("\nProjector interrupted by user")
        sys.exit(0)
    except Exception as exc:
        print(f"Projector failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
