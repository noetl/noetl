from pathlib import Path


SCHEMA = Path("noetl/database/ddl/postgres/schema_ddl.sql")


def test_distributed_runtime_schema_contract_is_present():
    ddl = SCHEMA.read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS noetl.stage" in ddl
    assert "CREATE TABLE IF NOT EXISTS noetl.frame" in ddl
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
