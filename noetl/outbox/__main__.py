"""Command-line entrypoint for the NoETL outbox publisher."""

from __future__ import annotations

import argparse

from noetl.outbox.worker import (
    OutboxPublisherSettings,
    load_outbox_publisher_settings,
    run_outbox_publisher_sync,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="NoETL transactional outbox publisher")
    parser.add_argument("--batch-size", type=int, default=None, help="Rows to claim per publish batch")
    parser.add_argument("--idle-sleep", type=float, default=None, help="Sleep seconds when no rows are ready")
    parser.add_argument("--error-sleep", type=float, default=None, help="Sleep seconds after a publish loop error")
    parser.add_argument("--once", action="store_true", help="Publish one batch and exit")
    args = parser.parse_args()

    base = load_outbox_publisher_settings()
    settings = OutboxPublisherSettings(
        batch_size=args.batch_size if args.batch_size is not None else base.batch_size,
        idle_sleep_seconds=args.idle_sleep if args.idle_sleep is not None else base.idle_sleep_seconds,
        error_sleep_seconds=args.error_sleep if args.error_sleep is not None else base.error_sleep_seconds,
        once=args.once or base.once,
    )
    run_outbox_publisher_sync(settings=settings)


if __name__ == "__main__":
    main()

