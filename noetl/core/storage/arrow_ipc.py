"""Arrow IPC serialization helpers for tabular runtime frames."""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any, Iterable, Mapping, Optional


ARROW_STREAM_MEDIA_TYPE = "application/vnd.apache.arrow.stream"


def rows_to_arrow_ipc(
    rows: Iterable[Mapping[str, Any]],
    *,
    columns: Optional[list[str]] = None,
) -> tuple[bytes, str, int]:
    """Serialize row dictionaries to Arrow streaming IPC bytes.

    Returns ``(payload, schema_digest, row_count)``.  The digest is computed
    from Arrow's serialized schema, not from the row values, so consumers can
    cheaply check whether two frames share a logical shape.
    """
    try:
        import pyarrow as pa
    except Exception as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError("pyarrow is required for Arrow IPC frame serialization") from exc

    materialized_rows = [dict(row) for row in rows]
    if columns is None:
        seen: list[str] = []
        for row in materialized_rows:
            for key in row.keys():
                key_str = str(key)
                if key_str not in seen:
                    seen.append(key_str)
        columns = seen

    normalized_rows = [
        {column: row.get(column) for column in columns}
        for row in materialized_rows
    ]
    table = pa.Table.from_pylist(normalized_rows, schema=None)
    if columns:
        table = table.select([column for column in columns if column in table.column_names])

    sink = BytesIO()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    payload = sink.getvalue()
    schema_digest = hashlib.sha256(table.schema.serialize().to_pybytes()).hexdigest()
    return payload, schema_digest, len(materialized_rows)


def arrow_ipc_to_rows(payload: bytes) -> list[dict[str, Any]]:
    """Decode Arrow streaming IPC bytes back into Python row dictionaries."""
    try:
        import pyarrow as pa
    except Exception as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError("pyarrow is required for Arrow IPC frame deserialization") from exc

    with pa.ipc.open_stream(payload) as reader:
        table = reader.read_all()
    return table.to_pylist()


__all__ = ["ARROW_STREAM_MEDIA_TYPE", "rows_to_arrow_ipc", "arrow_ipc_to_rows"]
