#!/usr/bin/env python3
"""Runner for the synthetic BHS state-report load test fixture."""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests
import yaml

PLAYBOOK_FILE = Path(
    "tests/fixtures/playbooks/load_test/bhs_state_report_synthetic_load/"
    "bhs_state_report_synthetic_load.yaml"
)


def post_json(base_url: str, path: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    response = requests.post(f"{base_url}{path}", json=payload, timeout=timeout)
    response.raise_for_status()
    return response.json()


def query_postgres(base_url: str, query: str) -> list[Any]:
    data = post_json(base_url, "/api/postgres/execute", {"query": query, "schema": "noetl"}, timeout=60.0)
    if str(data.get("status", "")).lower() == "error":
        raise RuntimeError(f"postgres query failed: {data.get('error')}")
    return data.get("result", [])


def register_playbook(base_url: str) -> dict[str, Any]:
    playbook = yaml.safe_load(PLAYBOOK_FILE.read_text(encoding="utf-8"))
    result = post_json(
        base_url,
        "/api/catalog/register",
        {"path": playbook["metadata"]["path"], "content": PLAYBOOK_FILE.read_text(encoding="utf-8")},
        timeout=60.0,
    )
    return {"playbook": playbook, "result": result}


def execute_playbook(base_url: str, path: str, total_items: int, batch_size: int, concurrent_batches: int, items_max_in_flight: int) -> int:
    payload = {
        "path": path,
        "payload": {
            "total_items": int(total_items),
            "batch_size": int(batch_size),
            "concurrent_batches": int(concurrent_batches),
            "items_max_in_flight": int(items_max_in_flight),
        },
    }
    result = post_json(base_url, "/api/execute", payload, timeout=60.0)
    execution_id = result.get("execution_id")
    if execution_id is None:
        raise RuntimeError(f"missing execution_id in execute response: {result}")
    return int(execution_id)


def wait_for_completion(base_url: str, execution_id: int, timeout: int) -> tuple[str, int]:
    deadline = time.time() + timeout
    event_count = 0
    while time.time() < deadline:
        rows = query_postgres(
            base_url,
            f"""
            SELECT event_type, node_name, status
            FROM noetl.event
            WHERE execution_id = {execution_id}
            ORDER BY event_id DESC
            LIMIT 100
            """,
        )
        event_count = len(rows)
        for row in rows:
            event_type = row[0] if isinstance(row, list) else row.get("event_type")
            if event_type in ("playbook.completed", "playbook_completed", "workflow.completed", "workflow_completed"):
                return "completed", event_count
            if event_type in ("playbook.failed", "playbook_failed", "workflow.failed", "workflow_failed"):
                return "failed", event_count
        time.sleep(2)
    return "timeout", event_count


def fetch_summary(base_url: str, execution_id: int) -> dict[str, Any] | None:
    rows = query_postgres(
        base_url,
        f"""
        SELECT result
        FROM noetl.event
        WHERE execution_id = {execution_id}
          AND node_name = 'summarize'
          AND event_type = 'step.exit'
          AND result IS NOT NULL
        ORDER BY event_id DESC
        LIMIT 1
        """,
    )
    if not rows:
        return None
    raw = rows[0][0] if isinstance(rows[0], list) else rows[0].get("result")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw}
    return raw


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the synthetic BHS state-report load test")
    parser.add_argument("--base-url", default="http://localhost:8082")
    parser.add_argument("--total-items", type=int, default=540)
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--concurrent-batches", type=int, default=1)
    parser.add_argument("--items-max-in-flight", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args()

    print("=" * 60)
    print("BHS STATE REPORT SYNTHETIC LOAD TEST")
    print("=" * 60)
    print(f"Base URL: {args.base_url}")
    print(f"Total items: {args.total_items}")
    print(f"Batch size: {args.batch_size}")
    print(f"Concurrent batches: {args.concurrent_batches}")
    print(f"Items max in flight: {args.items_max_in_flight}")
    print("=" * 60)

    registered = register_playbook(args.base_url)
    path = registered["playbook"]["metadata"]["path"]
    print(f"Registered: {path}")

    execution_id = execute_playbook(
        args.base_url,
        path,
        args.total_items,
        args.batch_size,
        args.concurrent_batches,
        args.items_max_in_flight,
    )
    print(f"Execution ID: {execution_id}")

    status, event_count = wait_for_completion(args.base_url, execution_id, args.timeout)
    print(f"Final status: {status}")
    print(f"Observed events: {event_count}")

    summary = fetch_summary(args.base_url, execution_id)
    if summary:
        print(json.dumps(summary, indent=2, sort_keys=True))

    return 0 if status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
