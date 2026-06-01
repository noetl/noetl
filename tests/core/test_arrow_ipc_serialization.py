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


def test_rows_to_arrow_ipc_handles_mixed_type_column():
    """Regression for noetl/ai-meta#36.

    When `rows_to_arrow_ipc` was called with mixed-type column values
    (e.g. the first row's `id` is an int but later rows have it as a
    string), `pa.Table.from_pylist(rows, schema=None)` would error out
    with ``Could not convert <value> with type str: tried to convert
    to int64`` — bubbling up to the server's `events.batch` projector
    and surfacing as ``batch.failed`` with `error_code=processing_error`.

    The fix coerces any mixed-type column to string so the encode
    succeeds.  Pure-typed columns keep their natural Arrow type.
    """
    from noetl.core.storage import arrow_ipc_to_rows, rows_to_arrow_ipc

    rows = [
        # First row's `id` is an int — pyarrow's per-column inference
        # would pick int64 for the column from this row alone.
        {"id": 1, "username": "user_1", "password": "[REDACTED]"},
        # Second row's `id` is a str — would have crashed the encoder
        # before the fix.
        {"id": "two", "username": "user_2", "password": "[REDACTED]"},
        # Third row's `id` is None — must not affect inference.
        {"id": None, "username": "user_3", "password": "[REDACTED]"},
    ]

    payload, schema_digest, row_count = rows_to_arrow_ipc(rows)

    assert payload
    assert len(schema_digest) == 64
    assert row_count == 3

    # Round-trip — `id` is now a string column (coerced because it was
    # mixed-type); `username` and `password` stay strings.
    decoded = arrow_ipc_to_rows(payload)
    assert decoded[0]["id"] == "1"
    assert decoded[1]["id"] == "two"
    assert decoded[2]["id"] is None
    assert decoded[0]["username"] == "user_1"
    assert decoded[2]["password"] == "[REDACTED]"


def test_rows_to_arrow_ipc_pure_typed_columns_unaffected():
    """The mixed-type fix must not regress the fast path.

    When all columns are pure-typed, the encode must still produce the
    natural Arrow types (int64 stays int64, bool stays bool) — the
    string-coercion fallback only fires for mixed columns.
    """
    from noetl.core.storage import arrow_ipc_to_rows, rows_to_arrow_ipc

    rows = [
        {"id": 1, "name": "Ada", "score": 1.5, "active": True},
        {"id": 2, "name": "Grace", "score": 2.5, "active": False},
        {"id": 3, "name": None, "score": 3.5, "active": True},
    ]

    payload, _digest, _count = rows_to_arrow_ipc(rows)
    decoded = arrow_ipc_to_rows(payload)

    # Types preserved: id is still int, score still float, active
    # still bool.  No string coercion applied.
    assert decoded[0]["id"] == 1 and isinstance(decoded[0]["id"], int)
    assert decoded[0]["score"] == 1.5 and isinstance(decoded[0]["score"], float)
    assert decoded[0]["active"] is True
    assert decoded[1]["active"] is False
    assert decoded[2]["name"] is None


def test_rows_to_arrow_feather_handles_mixed_type_column():
    """Same regression as #36 for the Feather encoder.

    `rows_to_arrow_feather` shares the underlying `pa.Table.from_pylist`
    pattern; the safety helper is wired into both.
    """
    from noetl.core.storage import arrow_feather_to_rows, rows_to_arrow_feather

    rows = [
        {"id": 1, "label": "alpha"},
        {"id": "two", "label": "beta"},
    ]

    payload, _digest, row_count = rows_to_arrow_feather(rows)
    decoded = arrow_feather_to_rows(payload)

    assert row_count == 2
    assert decoded[0]["id"] == "1"
    assert decoded[1]["id"] == "two"
