"""Arrow IPC serialization helpers for tabular runtime frames."""

from __future__ import annotations

import hashlib
import logging
from io import BytesIO
from typing import Any, Iterable, Mapping, Optional


ARROW_STREAM_MEDIA_TYPE = "application/vnd.apache.arrow.stream"
ARROW_FEATHER_MEDIA_TYPE = "application/vnd.apache.arrow.file"


logger = logging.getLogger(__name__)


def _build_safe_arrow_table(rows: list[dict[str, Any]], columns: list[str]):
    """Build a `pa.Table` from row dicts, tolerating mixed-type columns.

    The default `pa.Table.from_pylist(rows, schema=None)` infers a single
    Arrow type per column from the first non-None value, then errors out
    on any later value that can't be cast to that type.  Real-world
    DuckDB rowsets surface mixed-type columns in two shapes:

    - **Tool-output coercion**: numeric IDs that show up as `int` in some
      rows and `str` in others when the source rowset was produced via
      `'user_' || i AS username` and a downstream serializer lifted
      `username='1'` into `username=1` for the first row (e.g. when
      DuckDB's `as_objects: true` emits typed scalars).
    - **Credential scrubber**: the producer-side scrubber substitutes
      `"[REDACTED]"` (a str) for whatever type the column originally
      carried; for columns where some rows escape scrubbing (different
      credential-key matching), the post-scrub column is mixed.

    The previous behaviour was to let `from_pylist` fail with
    ``Could not convert <value> with type <T>: tried to convert to <U>``.
    That bubbles up to the server's `events.batch` projector and surfaces
    as ``batch.failed`` with `error_code=processing_error`, halting the
    entire workflow.  See noetl/ai-meta#36.

    Strategy: pre-scan rows once, compute an explicit schema where any
    column whose values span more than one inferred Arrow type is
    downgraded to ``pa.string()`` (with values stringified).  Pure-type
    columns keep their natural Arrow type — the slow path only fires
    for columns that genuinely mix types.
    """
    import pyarrow as pa

    try:
        return pa.Table.from_pylist(rows, schema=None)
    except (pa.ArrowInvalid, pa.ArrowTypeError) as exc:
        logger.debug(
            "[ARROW-IPC] Falling back to string-coerced schema for mixed-type "
            "columns: %s",
            exc,
        )

    # Per-column type observation.  `None` values are skipped — they're
    # nullable in any Arrow schema.  `bool` is checked before `int`
    # because `bool` is a subclass of `int` in Python.
    type_groups: dict[str, set[str]] = {col: set() for col in columns}
    for row in rows:
        for col in columns:
            value = row.get(col)
            if value is None:
                continue
            if isinstance(value, bool):
                type_groups[col].add("bool")
            elif isinstance(value, int):
                type_groups[col].add("int")
            elif isinstance(value, float):
                type_groups[col].add("float")
            elif isinstance(value, str):
                type_groups[col].add("str")
            elif isinstance(value, (list, dict)):
                type_groups[col].add("nested")
            else:
                type_groups[col].add("other")

    mixed_columns: set[str] = {
        col for col, types in type_groups.items() if len(types) > 1
    }

    # Cross-row mixed-type case: stringify just the offending columns,
    # keep pure-typed columns at their natural Arrow type.  Fast path
    # for the common DuckDB-rowset shape that triggered the original
    # bug.
    if mixed_columns:
        coerced_rows = []
        for row in rows:
            new_row = dict(row)
            for col in mixed_columns:
                value = new_row.get(col)
                if value is None:
                    continue
                new_row[col] = str(value)
            coerced_rows.append(new_row)

        logger.info(
            "[ARROW-IPC] Coerced %d mixed-type column(s) to string: %s",
            len(mixed_columns),
            sorted(mixed_columns),
        )
        try:
            return pa.Table.from_pylist(coerced_rows, schema=None)
        except (pa.ArrowInvalid, pa.ArrowTypeError):
            # Fall through to the nested-column case below.
            pass

    # Nested mixed-type case: no cross-row column variance (or even
    # after the simple stringification the encode still fails), so the
    # offending types are nested INSIDE one of the column values — e.g.
    # the outbox encodes a single-row table where one column carries a
    # nested `result.context.data.rows` list whose elements have mixed
    # types for the same field across rows.  Stringify (via JSON) every
    # non-scalar column value so pyarrow only has to infer string/int/
    # float/bool primitives.  Last-resort fallback; logged at INFO so
    # operators see when it fires.
    import json as _json

    nested_columns: set[str] = set()
    nested_rows = []
    for row in rows:
        new_row = dict(row)
        for col, value in list(new_row.items()):
            if isinstance(value, (dict, list)):
                nested_columns.add(col)
                try:
                    new_row[col] = _json.dumps(value, default=str, sort_keys=True)
                except (TypeError, ValueError):
                    new_row[col] = str(value)
        nested_rows.append(new_row)

    if nested_columns:
        logger.info(
            "[ARROW-IPC] JSON-stringified %d nested column(s) for Arrow encoding: %s",
            len(nested_columns),
            sorted(nested_columns),
        )

    return pa.Table.from_pylist(nested_rows, schema=None)


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
    # Use the mixed-type-tolerant builder instead of the bare `from_pylist`
    # call.  Pure-typed columns hit the fast path inside the helper; only
    # genuinely mixed columns pay the per-row coercion cost.  See
    # `_build_safe_arrow_table` for the rationale (noetl/ai-meta#36).
    table = _build_safe_arrow_table(normalized_rows, columns)
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


def rows_to_arrow_feather(
    rows: Iterable[Mapping[str, Any]],
    *,
    columns: Optional[list[str]] = None,
) -> tuple[bytes, str, int]:
    """Serialize row dictionaries to Arrow Feather/file bytes."""
    try:
        import pyarrow as pa
        import pyarrow.feather as feather
    except Exception as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError("pyarrow is required for Arrow Feather serialization") from exc

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
    # See `_build_safe_arrow_table` (noetl/ai-meta#36).
    table = _build_safe_arrow_table(normalized_rows, columns)
    if columns:
        table = table.select([column for column in columns if column in table.column_names])

    sink = BytesIO()
    feather.write_feather(table, sink)
    payload = sink.getvalue()
    schema_digest = hashlib.sha256(table.schema.serialize().to_pybytes()).hexdigest()
    return payload, schema_digest, len(materialized_rows)


def arrow_feather_to_rows(payload: bytes) -> list[dict[str, Any]]:
    """Decode Arrow Feather/file bytes back into Python row dictionaries."""
    try:
        import pyarrow.feather as feather
    except Exception as exc:  # pragma: no cover - exercised when optional dep missing
        raise RuntimeError("pyarrow is required for Arrow Feather deserialization") from exc

    return feather.read_table(BytesIO(payload)).to_pylist()


__all__ = [
    "ARROW_FEATHER_MEDIA_TYPE",
    "ARROW_STREAM_MEDIA_TYPE",
    "arrow_feather_to_rows",
    "arrow_ipc_to_rows",
    "rows_to_arrow_feather",
    "rows_to_arrow_ipc",
]
