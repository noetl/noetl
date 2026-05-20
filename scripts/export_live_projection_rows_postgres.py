#!/usr/bin/env python
"""Export live projection rows from the reference Postgres adapter.

The JSON this script writes is the stable validation contract. Postgres is only
the current adapter used to read live rows; replay validation consumes the
adapter-neutral row JSON through scripts/build_live_projection_checksums.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from noetl.core.common import get_pgdb_connection

SURFACES = ("execution", "stages", "frames", "commands", "business_objects", "loops")

EXECUTION_SQL = """
WITH event_rollup AS (
    SELECT
        execution_id,
        count(*)::bigint AS event_count,
        max(event_id) AS max_event_id,
        jsonb_agg(payload_ref ORDER BY event_id) FILTER (WHERE payload_ref IS NOT NULL) AS payload_refs
    FROM noetl.event
    WHERE execution_id = %s
      AND tenant_id = %s
      AND organization_id = %s
    GROUP BY execution_id
)
SELECT
    e.execution_id,
    %s::text AS tenant_id,
    %s::text AS organization_id,
    %s::text AS projection,
    e.status,
    e.last_node_name,
    COALESCE(e.last_event_id, er.max_event_id) AS last_event_id,
    e.last_event_type,
    COALESCE(er.event_count, 0) AS event_count,
    COALESCE(er.payload_refs, '[]'::jsonb) AS payload_refs,
    NULL::text AS upcaster_registry_digest
FROM noetl.execution e
LEFT JOIN event_rollup er ON er.execution_id = e.execution_id
WHERE e.execution_id = %s
"""

STAGE_SQL = """
WITH frame_rollup AS (
    SELECT
        stage_id,
        count(*)::bigint AS frame_count,
        COALESCE(sum(row_count), 0)::bigint AS row_count,
        COALESCE(sum(events_emitted), 0)::bigint AS events_emitted,
        count(*) FILTER (WHERE status IN ('FAILED', 'ABANDONED'))::bigint AS failed_count
    FROM noetl.frame
    WHERE execution_id = %s
      AND tenant_id = %s
      AND organization_id = %s
    GROUP BY stage_id
),
event_rollup AS (
    SELECT
        stage_id,
        max(event_id) AS last_event_id
    FROM noetl.event
    WHERE execution_id = %s
      AND tenant_id = %s
      AND organization_id = %s
      AND stage_id IS NOT NULL
    GROUP BY stage_id
)
SELECT
    s.stage_id,
    s.status,
    s.kind,
    s.step_name,
    s.parent_stage_id,
    s.loop_event_id,
    s.opened_event_id,
    s.closed_event_id,
    COALESCE(fr.frame_count, 0) AS frame_count,
    COALESCE(fr.row_count, 0) AS row_count,
    COALESCE(fr.events_emitted, 0) AS events_emitted,
    COALESCE(fr.failed_count, 0) AS failed_count,
    COALESCE(er.last_event_id, s.closed_event_id, s.opened_event_id) AS last_event_id
FROM noetl.stage s
LEFT JOIN frame_rollup fr ON fr.stage_id = s.stage_id
LEFT JOIN event_rollup er ON er.stage_id = s.stage_id
WHERE s.execution_id = %s
  AND s.tenant_id = %s
  AND s.organization_id = %s
ORDER BY s.stage_id
"""

FRAME_SQL = """
SELECT
    frame_id,
    stage_id,
    parent_frame_id,
    command_id,
    claimed_event_id,
    terminal_event_id,
    status,
    row_count,
    cursor,
    events_emitted,
    output_ref
FROM noetl.frame
WHERE execution_id = %s
  AND tenant_id = %s
  AND organization_id = %s
ORDER BY frame_id
"""

COMMAND_SQL = """
WITH command_events AS (
    SELECT
        command_id,
        max(event_id) FILTER (WHERE event_type = 'command.claimed') AS claimed_event_id,
        max(event_id) FILTER (WHERE event_type = 'command.started') AS started_event_id,
        max(event_id) FILTER (
            WHERE event_type IN (
                'command.completed',
                'command.failed',
                'command.cancelled',
                'command.timed_out',
                'command.timeout'
            )
        ) AS terminal_event_id
    FROM noetl.event
    WHERE execution_id = %s
      AND tenant_id = %s
      AND organization_id = %s
      AND command_id IS NOT NULL
    GROUP BY command_id
)
SELECT
    c.command_id,
    c.stage_id,
    c.frame_id,
    c.parent_command_id,
    c.worker_id,
    c.meta->>'worker_locator' AS worker_locator,
    COALESCE(c.meta->'locality', '{}'::jsonb) AS locality,
    COALESCE(c.meta->'source_locality', '{}'::jsonb) AS source_locality,
    COALESCE(c.meta->'placement', '{}'::jsonb) AS placement,
    c.status,
    c.event_id AS issued_event_id,
    ce.claimed_event_id,
    ce.started_event_id,
    COALESCE(ce.terminal_event_id, c.latest_event_id) AS terminal_event_id
FROM noetl.command c
LEFT JOIN command_events ce ON ce.command_id = c.command_id
WHERE c.execution_id = %s
ORDER BY c.command_id
"""

PROJECTION_SQL = """
SELECT state
FROM noetl.projection
WHERE tenant_id = %s
  AND organization_id = %s
  AND projection_id = %s
ORDER BY updated_at DESC
LIMIT 1
"""


def _json_default(value: Any) -> str | int | float:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical_checksum(value: Any) -> str:
    normalized = json.loads(json.dumps(value, default=_json_default, sort_keys=True))
    rendered = json.dumps(normalized, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _connect(dsn: str | None):
    conninfo = dsn or os.getenv("NOETL_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not conninfo:
        conninfo = get_pgdb_connection()
    return psycopg.connect(conninfo, row_factory=dict_row)


def _select_all(conn, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]


def _rows_from_projection_state(
    state: Mapping[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(state, Mapping):
        return [], []

    business_objects = state.get("business_objects")
    business_rows: list[dict[str, Any]] = []
    if isinstance(business_objects, Mapping):
        for object_key, row in business_objects.items():
            if isinstance(row, Mapping):
                business_rows.append(
                    {"object_key": row.get("object_key") or object_key, **dict(row)}
                )

    loops = state.get("loops")
    loop_rows: list[dict[str, Any]] = []
    if isinstance(loops, Mapping):
        for loop_id, row in loops.items():
            if isinstance(row, Mapping):
                loop_rows.append({"loop_id": row.get("loop_id") or loop_id, **dict(row)})

    return business_rows, loop_rows


def export_live_projection_rows(
    conn,
    *,
    execution_id: int,
    tenant_id: str,
    organization_id: str,
    projection: str,
) -> dict[str, list[dict[str, Any]]]:
    execution_rows = _select_all(
        conn,
        EXECUTION_SQL,
        (
            execution_id,
            tenant_id,
            organization_id,
            tenant_id,
            organization_id,
            projection,
            execution_id,
        ),
    )
    stage_rows = _select_all(
        conn,
        STAGE_SQL,
        (
            execution_id,
            tenant_id,
            organization_id,
            execution_id,
            tenant_id,
            organization_id,
            execution_id,
            tenant_id,
            organization_id,
        ),
    )
    frame_rows = _select_all(
        conn,
        FRAME_SQL,
        (execution_id, tenant_id, organization_id),
    )
    command_rows = _select_all(
        conn,
        COMMAND_SQL,
        (execution_id, tenant_id, organization_id, execution_id),
    )
    projection_rows = _select_all(
        conn,
        PROJECTION_SQL,
        (tenant_id, organization_id, f"execution/{execution_id}/{projection}"),
    )
    projection_state = projection_rows[0].get("state") if projection_rows else None
    business_rows, loop_rows = _rows_from_projection_state(projection_state)

    return {
        "execution": execution_rows,
        "stages": stage_rows,
        "frames": frame_rows,
        "commands": command_rows,
        "business_objects": business_rows,
        "loops": loop_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export NoETL live projection rows from the reference Postgres adapter",
    )
    parser.add_argument("--execution-id", required=True, type=int)
    parser.add_argument("--tenant-id", default="default")
    parser.add_argument("--organization-id", default="default")
    parser.add_argument("--projection", default="all")
    parser.add_argument("--dsn", help="Optional Postgres connection string; defaults to NoETL env")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    with _connect(args.dsn) as conn:
        rows = export_live_projection_rows(
            conn,
            execution_id=args.execution_id,
            tenant_id=args.tenant_id,
            organization_id=args.organization_id,
            projection=args.projection,
        )

    payload = {
        "schema_version": 1,
        "adapter": "postgres",
        "execution_id": args.execution_id,
        "tenant_id": args.tenant_id,
        "organization_id": args.organization_id,
        "projection": args.projection,
        "exported_at": _utc_now(),
        "rows": rows,
        "row_counts": {surface: len(rows[surface]) for surface in SURFACES},
        "rows_checksum": _canonical_checksum(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({"output": str(args.output), "row_counts": payload["row_counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
