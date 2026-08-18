from pathlib import Path


SCHEMA = Path("noetl/database/ddl/postgres/schema_ddl.sql")


def test_distributed_runtime_schema_contract_is_present():
    ddl = SCHEMA.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS noetl.stage" in ddl
    assert "CREATE TABLE IF NOT EXISTS noetl.frame" in ddl
    assert "CREATE TABLE IF NOT EXISTS noetl.outbox" in ddl
    assert "CREATE TABLE IF NOT EXISTS noetl.projection" in ddl
    assert "CREATE TABLE IF NOT EXISTS noetl.projection_snapshot" in ddl
    assert "CREATE INDEX IF NOT EXISTS frame_open_idx" in ddl
    assert "CREATE INDEX IF NOT EXISTS idx_frame_stage_cursor_slot_index" in ddl
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_frame_claim_key_unique" in ddl
    assert "CREATE INDEX IF NOT EXISTS idx_frame_idempotent_claim" in ddl
    assert "CREATE INDEX IF NOT EXISTS idx_projection_tenant_type" in ddl

    for column in [
        "tenant_id",
        "organization_id",
        "stream_id",
        "stream_version",
        "aggregate_id",
        "aggregate_type",
        "schema_name",
        "schema_version",
        "event_time",
        "ingest_time",
        "producer",
        "causation_id",
        "correlation_id",
        "idempotency_key",
        "payload_ref",
        "envelope_checksum",
    ]:
        assert f"ADD COLUMN IF NOT EXISTS {column}" in ddl

    assert "idx_event_tenant_org_execution_event_id" in ddl
    assert "idx_event_stream_version" in ddl
    assert "idx_event_aggregate_event_id" in ddl
    assert "idx_outbox_ready" in ddl


def test_command_lookup_by_event_id_has_an_index():
    """`POST /api/commands/{event_id}/claim` resolves by `event_id` alone.

    `noetl.command` is HASH-partitioned on `execution_id`, and every other
    index on it leads with that column, so an `event_id`-only predicate cannot
    use any of them -- the planner falls back to a parallel seq scan of all 16
    partitions.  That cost ~295ms per claim on a 428k-row table and was paid
    twice per playbook hop, which measured as ~79% of a turn's wall clock
    (noetl/ai-meta#155).

    Asserted as a property (an index whose leading column is `event_id`)
    rather than by name, so renaming the index keeps the guard honest while
    dropping it fails.
    """
    ddl = SCHEMA.read_text(encoding="utf-8")

    statements = [
        " ".join(stmt.split())
        for stmt in ddl.split(";")
        if "ON NOETL.COMMAND" in " ".join(stmt.split()).upper()
        and "CREATE INDEX" in " ".join(stmt.split()).upper()
    ]
    leading_event_id = [
        stmt for stmt in statements if "(event_id" in stmt.replace(" (", "(")
    ]
    assert leading_event_id, (
        "noetl.command needs an index whose leading column is event_id; "
        "without it every command claim seq-scans all 16 partitions. "
        f"Indexes found on noetl.command: {statements}"
    )
