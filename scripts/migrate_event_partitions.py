#!/usr/bin/env python3
"""
Migrate noetl.event to a range-partitioned table keyed on execution_id.

Partition boundaries are derived from the snowflake ID epoch (Jan 1 2024):
  id = (elapsed_ms << 22) | node_id_bits | seq
so each quarter ≈ 33 trillion IDs.

Run against the live GKE cluster via the NoETL API using the postgres superuser.
"""
import json
import subprocess
import sys

API_URL = "http://localhost:8082/api/postgres/execute"
PG_CONN  = "postgresql://postgres:demo@pgbouncer.postgres.svc.cluster.local:5432/noetl"

# Partition boundaries (from id_for_date() calc with epoch=2024-01-01)
#   2026-01-01:  264_905_529_753_600_000
#   2026-04-01:  297_520_437_657_600_000
#   2026-07-01:  330_497_733_427_200_000
#   2026-10-01:  363_837_417_062_400_000
#   2027-01-01:  397_177_100_697_600_000
#   2027-07-01:  462_769_304_371_200_000
#   2028-01-01:  529_448_671_641_600_000

STEPS = [
    ("Drop old table (cascade drops all indexes)",
     "DROP TABLE IF EXISTS noetl.event CASCADE"),

    ("Create partitioned event table",
     """CREATE TABLE noetl.event (
    execution_id        BIGINT,
    catalog_id          BIGINT NOT NULL REFERENCES noetl.catalog(catalog_id),
    event_id            BIGINT,
    parent_event_id     BIGINT,
    parent_execution_id BIGINT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_type          VARCHAR,
    node_id             VARCHAR,
    node_name           VARCHAR,
    node_type           VARCHAR,
    status              VARCHAR,
    duration            DOUBLE PRECISION,
    context             JSONB,
    result              JSONB,
    meta                JSONB,
    error               TEXT,
    current_index       INTEGER,
    current_item        TEXT,
    worker_id           VARCHAR,
    distributed_state   VARCHAR,
    context_key         VARCHAR,
    context_value       TEXT,
    trace_component     JSONB,
    stack_trace         TEXT,
    PRIMARY KEY (execution_id, event_id)
) PARTITION BY RANGE (execution_id)"""),

    ("Grant privileges to noetl user",
     "GRANT ALL PRIVILEGES ON TABLE noetl.event TO noetl"),

    ("Partition: pre_2026 (MINVALUE → 2026-01-01)",
     "CREATE TABLE noetl.event_pre_2026 PARTITION OF noetl.event "
     "FOR VALUES FROM (MINVALUE) TO (264905529753600000)"),

    ("Partition: 2026_q1 (2026-01-01 → 2026-04-01)",
     "CREATE TABLE noetl.event_2026_q1 PARTITION OF noetl.event "
     "FOR VALUES FROM (264905529753600000) TO (297520437657600000)"),

    ("Partition: 2026_q2 (2026-04-01 → 2026-07-01)",
     "CREATE TABLE noetl.event_2026_q2 PARTITION OF noetl.event "
     "FOR VALUES FROM (297520437657600000) TO (330497733427200000)"),

    ("Partition: 2026_q3 (2026-07-01 → 2026-10-01)",
     "CREATE TABLE noetl.event_2026_q3 PARTITION OF noetl.event "
     "FOR VALUES FROM (330497733427200000) TO (363837417062400000)"),

    ("Partition: 2026_q4 (2026-10-01 → 2027-01-01)",
     "CREATE TABLE noetl.event_2026_q4 PARTITION OF noetl.event "
     "FOR VALUES FROM (363837417062400000) TO (397177100697600000)"),

    ("Partition: 2027_h1 (2027-01-01 → 2027-07-01)",
     "CREATE TABLE noetl.event_2027_h1 PARTITION OF noetl.event "
     "FOR VALUES FROM (397177100697600000) TO (462769304371200000)"),

    ("Partition: 2027_h2 (2027-07-01 → 2028-01-01)",
     "CREATE TABLE noetl.event_2027_h2 PARTITION OF noetl.event "
     "FOR VALUES FROM (462769304371200000) TO (529448671641600000)"),

    # Catch-all: covers old-epoch IDs (~570T+) and anything beyond 2028
    ("Partition: default (everything else)",
     "CREATE TABLE noetl.event_default PARTITION OF noetl.event DEFAULT"),

    ("Index: execution_id",
     "CREATE INDEX idx_event_execution_id ON noetl.event (execution_id)"),

    ("Index: catalog_id",
     "CREATE INDEX idx_event_catalog_id ON noetl.event (catalog_id)"),

    ("Index: event_type",
     "CREATE INDEX idx_event_type ON noetl.event (event_type)"),

    ("Index: status",
     "CREATE INDEX idx_event_status ON noetl.event (status)"),

    ("Index: created_at",
     "CREATE INDEX idx_event_created_at ON noetl.event (created_at)"),

    ("Index: node_name",
     "CREATE INDEX idx_event_node_name ON noetl.event (node_name)"),

    ("Index: parent_event_id",
     "CREATE INDEX idx_event_parent_event_id ON noetl.event (parent_event_id)"),

    ("Index: parent_execution_id",
     "CREATE INDEX idx_event_parent_execution_id ON noetl.event (parent_execution_id)"),

    ("Index: execution_id + event_id DESC (pagination)",
     "CREATE INDEX idx_event_exec_id_event_id_desc ON noetl.event (execution_id, event_id DESC)"),

    ("Index: execution_id + event_type (event filtering)",
     "CREATE INDEX idx_event_exec_type ON noetl.event (execution_id, event_type, event_id DESC)"),

    ("Index: playbook.initialized lookup (fast exec listing)",
     """CREATE INDEX idx_event_playbook_init_event_id_desc
    ON noetl.event (event_id DESC)
    INCLUDE (execution_id, catalog_id, parent_execution_id, created_at)
    WHERE event_type = 'playbook.initialized'"""),

    ("Grant SELECT on all partition children to noetl",
     "GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA noetl TO noetl"),
]


def get_pod() -> str:
    result = subprocess.run(
        ["kubectl", "get", "pod", "-n", "noetl", "-l", "app=noetl-server",
         "--no-headers", "-o", "name"],
        capture_output=True, text=True
    )
    pods = result.stdout.strip().split("\n")
    pod = pods[0].replace("pod/", "")
    return pod


def run_query(pod: str, sql: str) -> dict:
    payload = json.dumps({"query": sql, "connection_string": PG_CONN})
    cmd = [
        "kubectl", "exec", "-n", "noetl", pod, "--",
        "curl", "-sf", "-X", "POST", API_URL,
        "-H", "Content-Type: application/json",
        "--data-raw", payload
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return {"status": "error", "error": f"curl failed: {result.stderr}"}
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return {"status": "error", "error": f"JSON parse error: {e}\nraw: {result.stdout[:200]}"}


def main():
    pod = get_pod()
    print(f"Using pod: {pod}\n")

    failed = []
    for desc, sql in STEPS:
        print(f"  {desc}...", end=" ", flush=True)
        resp = run_query(pod, sql)
        if resp.get("status") == "ok":
            print("OK")
        else:
            err = resp.get("error", "unknown")
            print(f"FAILED: {err}")
            failed.append((desc, err))
            # Non-fatal: skip index failures but stop on table creation failures
            if "CREATE TABLE" in sql or "DROP TABLE" in sql or "PARTITION BY" in sql:
                print("\nFatal error in table DDL — aborting.")
                sys.exit(1)

    print(f"\nMigration complete. Failures: {len(failed)}")
    if failed:
        for desc, err in failed:
            print(f"  - {desc}: {err}")

    # Verify partitions exist
    print("\nVerifying partitions:")
    resp = run_query(pod, """
        SELECT parent.relname AS parent, child.relname AS partition,
               pg_get_expr(child.relpartbound, child.oid) AS bounds
        FROM pg_class parent
        JOIN pg_inherits ON pg_inherits.inhparent = parent.oid
        JOIN pg_class child ON pg_inherits.inhrelid = child.oid
        WHERE parent.relname = 'event'
        ORDER BY child.relname
    """)
    for row in resp.get("result", []):
        print(f"  {row['partition']:30s}  {row['bounds']}")


if __name__ == "__main__":
    main()
