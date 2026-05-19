from __future__ import annotations


def test_rows_to_arrow_ipc_round_trips_rows_and_schema_digest():
    from noetl.core.storage import arrow_ipc_to_rows, rows_to_arrow_ipc

    rows = [
        {"id": 1, "name": "Ada", "active": True},
        {"id": 2, "name": "Grace", "active": False},
    ]

    payload, schema_digest, row_count = rows_to_arrow_ipc(rows)

    assert payload
    assert len(schema_digest) == 64
    assert row_count == 2
    assert arrow_ipc_to_rows(payload) == rows


def test_rows_to_arrow_ipc_digest_is_schema_based_not_value_based():
    from noetl.core.storage import rows_to_arrow_ipc

    _, left_digest, _ = rows_to_arrow_ipc([{"id": 1, "name": "Ada"}])
    _, right_digest, _ = rows_to_arrow_ipc([{"id": 2, "name": "Grace"}])

    assert left_digest == right_digest


def test_rows_to_arrow_feather_round_trips_rows_and_schema_digest():
    from noetl.core.storage import arrow_feather_to_rows, rows_to_arrow_feather

    rows = [{"event_id": 1, "event_type": "workflow.completed", "status": "COMPLETED"}]

    payload, schema_digest, row_count = rows_to_arrow_feather(rows)

    assert payload
    assert len(schema_digest) == 64
    assert row_count == 1
    assert arrow_feather_to_rows(payload) == rows
