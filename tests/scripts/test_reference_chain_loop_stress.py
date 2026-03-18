#!/usr/bin/env python3
"""Neutral end-to-end stress runner for pagination + loop reference-chain behavior."""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

import requests
import yaml

PLAYBOOK_FILE = Path(
    "tests/fixtures/playbooks/load_test/reference_chain_loop_stress/reference_chain_loop_stress.yaml"
)


def post_json(base_url: str, path: str, payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    resp = requests.post(f"{base_url}{path}", json=payload, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def parse_first_value(rows: Any) -> Any:
    if not rows:
        return None
    first = rows[0]
    if isinstance(first, list):
        return first[0] if first else None
    if isinstance(first, dict):
        return next(iter(first.values()), None)
    return first


def query_postgres(base_url: str, query: str) -> Any:
    payload = {"query": query, "schema": "noetl"}
    data = post_json(base_url, "/api/postgres/execute", payload, timeout=60.0)
    return data.get("result", [])


def register_playbook(base_url: str) -> dict[str, Any]:
    with PLAYBOOK_FILE.open("r", encoding="utf-8") as fh:
        playbook = yaml.safe_load(fh)
    payload = {"content": json.dumps(playbook)}
    result = post_json(base_url, "/api/catalog/register", payload, timeout=60.0)
    return {"playbook": playbook, "result": result}


def execute_playbook(
    base_url: str,
    path: str,
    total_records: int,
    page_size: int,
    page_payload_kb: int,
) -> int:
    payload = {
        "path": path,
        "payload": {
            "total_records": int(total_records),
            "page_size": int(page_size),
            "page_payload_kb": int(page_payload_kb),
        },
    }
    result = post_json(base_url, "/api/execute", payload, timeout=60.0)
    execution_id = result.get("execution_id")
    if execution_id is None:
        raise RuntimeError(f"missing execution_id in execute response: {result}")
    return int(execution_id)


def _normalize_execution_status(last_event: str) -> Optional[str]:
    normalized = str(last_event or "").lower()
    if normalized in {
        "playbook.completed",
        "playbook_completed",
        "workflow.completed",
        "workflow_completed",
    }:
        return "completed"
    if normalized in {
        "playbook.failed",
        "playbook_failed",
        "workflow.failed",
        "workflow_failed",
    }:
        return "failed"
    return None


def _parse_metrics_row(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    if isinstance(row, (list, tuple)):
        return {
            "last_status_event": row[0] if len(row) > 0 else None,
            "iteration_count": row[1] if len(row) > 1 else 0,
            "event_count": row[2] if len(row) > 2 else 0,
        }
    return {}


def fetch_poll_metrics(base_url: str, execution_id: int) -> tuple[Optional[str], int, int]:
    rows = query_postgres(
        base_url,
        f"""
        SELECT
          COALESCE(MAX(CASE
            WHEN event_type IN (
              'playbook.completed',
              'playbook_completed',
              'playbook.failed',
              'playbook_failed',
              'workflow.completed',
              'workflow_completed',
              'workflow.failed',
              'workflow_failed'
            )
            THEN lower(event_type)
            ELSE NULL
          END), '') AS last_status_event,
          COALESCE(SUM(CASE
            WHEN node_name IN ('process_records', 'process_records:task_sequence')
             AND event_type = 'step.exit'
            THEN 1
            ELSE 0
          END), 0) AS iteration_count,
          COUNT(*) AS event_count
        FROM noetl.event
        WHERE execution_id = {execution_id}
        """,
    )
    row = _parse_metrics_row(rows[0] if rows else {})
    status = _normalize_execution_status(str(row.get("last_status_event") or ""))
    return status, int(row.get("iteration_count") or 0), int(row.get("event_count") or 0)


def unwrap_event_result(raw_result: Any) -> Any:
    value = raw_result
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value
    if isinstance(value, dict) and "kind" in value and "data" in value:
        value = value.get("data")
    if isinstance(value, dict) and "result" in value:
        return value.get("result")
    return value


def fetch_finalize_result(base_url: str, execution_id: int) -> dict[str, Any]:
    rows = query_postgres(
        base_url,
        f"""
        SELECT result
        FROM noetl.event
        WHERE execution_id = {execution_id}
          AND node_name = 'finalize'
          AND event_type = 'step.exit'
          AND result IS NOT NULL
        ORDER BY event_id DESC
        LIMIT 1
        """,
    )
    raw = parse_first_value(rows)
    result = unwrap_event_result(raw)
    if not isinstance(result, dict):
        raise RuntimeError(f"unexpected finalize result payload: {result}")
    return result


def is_terminal(status: Optional[str]) -> bool:
    if not status:
        return False
    return status.lower() in {"completed", "failed", "error"}


def run_test(args: argparse.Namespace) -> int:
    base_url = args.base_url.rstrip("/")

    print("=" * 72)
    print("REFERENCE CHAIN LOOP STRESS TEST")
    print("=" * 72)
    print(f"base_url={base_url}")
    print(
        f"total_records={args.total_records} page_size={args.page_size} "
        f"page_payload_kb={args.page_payload_kb}"
    )

    register_data = register_playbook(base_url)
    playbook = register_data["playbook"]
    path = playbook["metadata"]["path"]
    print(f"registered playbook path={path}")

    execution_id = execute_playbook(
        base_url,
        path,
        args.total_records,
        args.page_size,
        args.page_payload_kb,
    )
    print(f"execution_id={execution_id}")

    start = time.time()
    last_progress_at = start
    last_iteration_count = 0

    while True:
        elapsed = int(time.time() - start)
        status, iteration_count, event_count = fetch_poll_metrics(base_url, execution_id)

        if iteration_count > last_iteration_count:
            last_progress_at = time.time()
            last_iteration_count = iteration_count

        stalled_for = int(time.time() - last_progress_at)
        print(
            f"[t+{elapsed:04d}s] status={status or 'running'} "
            f"loop_step_exits={iteration_count} events={event_count} stalled_for={stalled_for}s"
        )

        if is_terminal(status):
            break

        if elapsed >= args.timeout:
            raise TimeoutError(f"timed out after {args.timeout}s")

        if stalled_for >= args.stall_seconds and iteration_count < args.total_records:
            raise RuntimeError(
                "progress appears stalled: "
                f"no new process_records step.exit for {stalled_for}s "
                f"(count={iteration_count}, expected={args.total_records})"
            )

        time.sleep(args.poll_seconds)

    if (status or "").lower() != "completed":
        raise RuntimeError(f"execution ended with non-completed status: {status}")

    finalize_result = fetch_finalize_result(base_url, execution_id)
    if finalize_result.get("status") != "ok":
        raise RuntimeError(f"finalize status is not ok: {finalize_result}")
    processed_total = int(finalize_result.get("processed_total", 0) or 0)
    if processed_total != int(args.total_records):
        raise RuntimeError(
            f"expected total={args.total_records}, got processed_total={processed_total} finalize={finalize_result}"
        )
    if not bool(finalize_result.get("chain_contract_ok", False)):
        raise RuntimeError(f"chain_contract_ok is false: {finalize_result}")

    print("-" * 72)
    print("PASS")
    print(f"execution_id={execution_id}")
    print(f"finalize={json.dumps(finalize_result, indent=2)}")
    print("=" * 72)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run neutral pagination+loop stress e2e test")
    parser.add_argument(
        "--base-url",
        default=os.getenv("NOETL_BASE_URL", "http://localhost:30082"),
        help="NoETL server base URL",
    )
    parser.add_argument("--total-records", type=int, default=382)
    parser.add_argument("--page-size", type=int, default=25)
    parser.add_argument("--page-payload-kb", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--stall-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    args = parser.parse_args()

    try:
        return run_test(args)
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
