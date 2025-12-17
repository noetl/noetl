# TODO

## Observability payload structure

- Correlation & per-request context → `event.meta.obs`
  - `correlation_id`, `request_id`, `source_system`, `tenant`, `client_request_id`, etc.
- OpenTelemetry trace fields → `event.trace_component`
  - `trace_id`, `span_id`, `parent_span_id`, `trace_flags`

event payload:
```json
{
  "event_type": "task_enqueued",
  "execution_id": 223207183775432704,
  "meta": {
    "obs": {
      "correlation_id": "01JEF5K6V6A1W…",
      "request_id": "r-2f9a…",
      "source_system": "api-gateway",
      "tenant": "acme"
    }
  },
  "trace_component": {
    "trace_id": "4fd0e9ee3e7c4c89b7e9c7d2d8798d9f",
    "span_id": "7ddc0c9a8453f137",
    "parent_span_id": "2b3a0a1f03c99c81",
    "trace_flags": 1
  }
}

```

## Indexing
create btree expression indexes for equality lookups, and an optional GIN for ad-hoc queries:
```sql
-- Correlation ID equality / prefix searches
CREATE INDEX IF NOT EXISTS idx_event_meta_corr
  ON noetl.event ( (meta->'obs'->>'correlation_id') );

CREATE INDEX IF NOT EXISTS idx_event_meta_req
  ON noetl.event ( (meta->'obs'->>'request_id') );

-- Trace ID equality
CREATE INDEX IF NOT EXISTS idx_event_trace_id
  ON noetl.event ( (trace_component->>'trace_id') );

-- Optional: wide GIN for flexible JSON queries (has key/contains)
CREATE INDEX IF NOT EXISTS idx_event_meta_gin
  ON noetl.event USING GIN (meta jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_event_trace_gin
  ON noetl.event USING GIN (trace_component jsonb_path_ops);

```

## Queries

Find all executions for a correlation:

```sql
SELECT aggregate_id AS execution_id, MIN(created_at) AS first_seen, MAX(created_at) AS last_seen
FROM noetl.event
WHERE event_type IS NOT NULL
  AND meta->'obs'->>'correlation_id' = $1
GROUP BY aggregate_id
ORDER BY last_seen DESC;

```

Rebuild one execution’s timeline:
```sql
SELECT created_at, event_type, node_name, status, meta->'obs'->>'correlation_id' AS correlation_id
FROM noetl.event
WHERE execution_id = $1
ORDER BY created_at, event_id;

```

Trace-centric search:

```sql
SELECT execution_id, created_at, event_type, trace_component
FROM noetl.event
WHERE trace_component->>'trace_id' = $1
ORDER BY created_at;

```

## Ingestion policy (API/gateway → event)

1. On ingress, canonical correlation:
    - `X-Correlation-Id` if valid → else `X-Request-Id` → else generate ULID/UUIDv7.
2. Echo `X-Correlation-Id` in responses.
3. Continue `traceparent` if present (fill `trace_component`); otherwise start a new trace.
4. When appending events, always include:
    - `meta.obs.correlation_id` and (optionally) `request_id`
    - `trace_component.trace_id`, `span_id`, `parent_span_id`
   
## basic validation without new columns, add lightweight CHECK constraints on JSONB:
```sql
ALTER TABLE noetl.event
  ADD CONSTRAINT chk_corr_len
  CHECK (coalesce(length(meta->'obs'->>'correlation_id'), 0) <= 128);

ALTER TABLE noetl.event
  ADD CONSTRAINT chk_trace_len
  CHECK (coalesce(length(trace_component->>'trace_id'), 0) IN (0, 32));

```

_(Adjust lengths to formatter—32 hex chars shown for a typical trace id.)_

- **No extra columns:** everything lives under meta/trace_component.
- **Fast filters:** expression indexes make equality queries as quick as native columns.
- **Standardization:** trace_component cleanly mirrors OpenTelemetry; meta.obs stays.
- **Future-proof:** we can add more context keys without migrations; GIN covers ad-hoc queries.