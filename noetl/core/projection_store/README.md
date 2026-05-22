# `noetl.core.projection_store`

Backend-neutral **projection (read-model) and snapshot store** with a
reference PostgreSQL adapter. Projections are folded from the
[event store](../event_store/README.md) by the
[projector worker](../../projector/README.md) and are the serving surface
for replay state and aggregate queries.

## Status

- **Port:** `ProjectionStore` Protocol with `save_projection` / `load_projection`
  / `query_projections` / `save_snapshot` / `load_snapshot` ([ports.py](ports.py))
- **Reference adapter:** `PostgresProjectionStore` against `noetl.projection`
  and `noetl.projection_snapshot` ([postgres.py](postgres.py))
- **Phase:** v2 distributed-runtime spec phase 2 surface + phase 5 port shape.

## Interface contract

```python
class ProjectionStore(Protocol):
    async def save_projection(self, record: ProjectionRecord) -> bool: ...
    async def load_projection(self, projection_id: str) -> Optional[ProjectionRecord]: ...
    async def query_projections(self, query: ProjectionQuery) -> list[ProjectionRecord]: ...
    async def save_snapshot(self, snapshot: ProjectionSnapshot) -> bool: ...
    async def load_snapshot(
        self, aggregate_id: str, *, aggregate_type: Optional[str] = None
    ) -> Optional[ProjectionSnapshot]: ...
```

- `save_projection` / `save_snapshot` are **version-monotonic upserts**: a
  write at version `V` is only applied when `V >= existing.version`. The
  method returns `True` when the row actually changed (insert or eligible
  update) and `False` when the write was a no-op stale replay. This makes
  the writes safe for at-least-once event delivery.
- `query_projections` supports filtering by `tenant_id`, `organization_id`,
  `projection_type`, and `execution_id` with a `limit` (default 100).
  Results come back in `(updated_at DESC, projection_id ASC)` order.

## Types

### `ProjectionRecord`

| Field | Type | Notes |
|---|---|---|
| `projection_id` | `str` | Primary key. Convention: `"<scope>/<id>/<projection>"` (e.g., `"execution/12345/all"`). |
| `projection_type` | `str` | Namespace for queries. Convention: `"<family>:<projection>"` (e.g., `"replay_state:all"`). |
| `state` | `dict` | JSONB body — the folded projection state. |
| `version` | `int` | Monotonic per `projection_id`. Usually set to last source event's `stream_version`. |
| `tenant_id` / `organization_id` | `str` | Multi-tenant scope. |
| `execution_id` | `int?` | NoETL execution this projection belongs to. |
| `source_event_id` | `int?` | Last event included in the fold. |
| `checksum` | `str?` | Optional SHA-256 over `state`. If `None`, `resolved_checksum()` computes it. |
| `meta` | `dict` | JSONB meta annotations (e.g., `projection_lag_ms`, `event_count`, `event_time_watermark`). |

### `ProjectionSnapshot`

Composite key `(tenant_id, organization_id, aggregate_type, aggregate_id)`.
Used for fast aggregate rebuild without replaying from event zero. Same
version-monotonic upsert semantics as projections.

### `ProjectionQuery`

```python
ProjectionQuery(
    tenant_id="...",
    organization_id="...",
    projection_type="replay_state:all",
    execution_id=12345,
    limit=100,
)
```

## Schema

The Postgres adapter creates two tables. DDL is bundled in `postgres.py`
(`_PROJECTION_DDL`) and applied by calling `ensure_schema()`.

```sql
CREATE TABLE noetl.projection (
    projection_id   TEXT PRIMARY KEY,
    projection_type TEXT NOT NULL,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    organization_id TEXT NOT NULL DEFAULT 'default',
    execution_id    BIGINT,
    version         BIGINT NOT NULL,
    source_event_id BIGINT,
    state           JSONB NOT NULL,
    checksum        TEXT  NOT NULL,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_projection_tenant_type
    ON noetl.projection (tenant_id, organization_id, projection_type);

CREATE INDEX idx_projection_execution
    ON noetl.projection (execution_id, projection_type)
    WHERE execution_id IS NOT NULL;

CREATE TABLE noetl.projection_snapshot (
    aggregate_id    TEXT NOT NULL,
    aggregate_type  TEXT NOT NULL,
    tenant_id       TEXT NOT NULL DEFAULT 'default',
    organization_id TEXT NOT NULL DEFAULT 'default',
    version         BIGINT NOT NULL,
    snapshot        JSONB NOT NULL,
    checksum        TEXT  NOT NULL,
    meta            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, organization_id, aggregate_type, aggregate_id)
);

CREATE INDEX idx_projection_snapshot_type
    ON noetl.projection_snapshot (tenant_id, organization_id, aggregate_type, version DESC);
```

The adapter's `ensure_schema()` is idempotent (`IF NOT EXISTS`) and is
called by the projector worker at startup. If the connected role lacks DDL
privilege, the projector logs a warning and continues against the
pre-existing schema — production deployments should pre-apply DDL via a
migration step rather than rely on the bootstrap.

## Idempotency

The version-monotonic `WHERE noetl.projection.version <= EXCLUDED.version`
clause in the upsert is the **load-bearing** invariant for at-least-once
event delivery:

- Replaying the same event sequence twice is safe — later versions overwrite,
  older versions are no-ops.
- Out-of-order delivery is safe — a stale event with version `V_old` arrives
  after the projection has advanced past it, and the write is dropped.
- `save_projection` returns `True` only when the row was actually written, so
  the projector worker can count "stale projection records" as a metric.

## Usage

```python
from noetl.core.projection_store import (
    PostgresProjectionStore,
    ProjectionQuery,
    ProjectionRecord,
)

store = PostgresProjectionStore()
await store.ensure_schema()

await store.save_projection(
    ProjectionRecord(
        projection_id="execution/12345/all",
        projection_type="replay_state:all",
        execution_id=12345,
        version=42,
        state={"status": "running", "steps_completed": 7},
        meta={"projection_lag_ms": 18},
    )
)

current = await store.load_projection("execution/12345/all")

recent = await store.query_projections(
    ProjectionQuery(
        projection_type="replay_state:all",
        tenant_id="default",
        limit=50,
    )
)
```

## Related

- [`noetl.core.event_store`](../event_store/README.md) — source of truth feeding projections
- [`noetl.projector`](../../projector/README.md) — durable consumer that calls `save_projection`
- `noetl.server.api.replay.service.fold_replay_state` — in-process folder reused by the out-of-process projector
- Spec: [noetl_distributed_runtime_spec.md](https://github.com/noetl/docs/blob/main/docs/features/noetl_distributed_runtime_spec.md)
