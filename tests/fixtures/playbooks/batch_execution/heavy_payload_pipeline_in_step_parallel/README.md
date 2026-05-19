# heavy_payload_pipeline_in_step_parallel

This fixture simulates large per-item payload processing in a looped `task_sequence` pipeline.

It is built to reproduce and analyze behavior where execution slows down or stalls around ~100 items when each iteration handles 200-300 KB payloads.

## What this fixture gives you

- `direct_stress` mode:
  - One large loop over all items.
  - Per-item pipeline: `python -> http -> python -> postgres`.
  - Highest pressure on loop state, worker memory, and event throughput.
- `chunked_optimal` mode (default):
  - Parent orchestrates bounded chunk windows.
  - Parent dispatches chunk workers in parallel (`max_in_flight: 3`).
  - Child worker processes each chunk with parallel per-item pipeline.
  - Better control over server and worker resource usage while increasing throughput.

## Fixture files

- Parent playbook:
  `tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/heavy_payload_pipeline_in_step_parallel.yaml`
- Chunk worker playbook:
  `tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_chunk_worker/heavy_payload_pipeline_chunk_worker.yaml`

## Prerequisites

- NoETL server and workers running in distributed mode.
- Postgres credential available (default `pg_k8s`).
- `noetl`, `kubectl`, and `jq` installed.
- API reachable directly or via port-forward.

If needed, port-forward in terminal A:

```bash
kubectl -n noetl port-forward svc/noetl 8082:8082
```

Terminal B defaults:

```bash
export NOETL_HOST=localhost
export NOETL_PORT=8082
```

## Register playbooks

Register worker first, then parent:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" catalog register \
  tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_chunk_worker/heavy_payload_pipeline_chunk_worker.yaml

noetl --host "$NOETL_HOST" --port "$NOETL_PORT" catalog register \
  tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel/heavy_payload_pipeline_in_step_parallel.yaml
```

## Dry-run

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" exec \
  catalog://tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel \
  -r distributed \
  --dry-run
```

## Smoke test (recommended first)

This is a quick verification with bounded data and parallel chunk-worker orchestration.

```bash
RUN_JSON="$(curl -sS -X POST "http://$NOETL_HOST:$NOETL_PORT/api/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel",
    "payload": {
      "execution_mode": "chunked_optimal",
      "seed_rows": 120,
      "batch_size": 30,
      "max_batches": 4,
      "payload_kb_per_item": 220,
      "details_api_url": "https://httpbin.org/anything/heavy-item-detail"
    }
  }')"

echo "$RUN_JSON" | jq .
export EXECUTION_ID="$(echo "$RUN_JSON" | jq -r '.execution_id')"
echo "EXECUTION_ID=$EXECUTION_ID"
```

Wait for completion:

```bash
while true; do
  STATUS_JSON="$(noetl --host "$NOETL_HOST" --port "$NOETL_PORT" status "$EXECUTION_ID" --json)"
  echo "$STATUS_JSON" | jq '{execution_id, completed, failed, current_step}'

  COMPLETED="$(echo "$STATUS_JSON" | jq -r '.completed')"
  FAILED="$(echo "$STATUS_JSON" | jq -r '.failed')"
  if [ "$COMPLETED" = "true" ] || [ "$FAILED" = "true" ]; then
    break
  fi
  sleep 5
done
```

## Stress test (simulate >100 heavy items)

Use `direct_stress` with a larger row count.

```bash
RUN_JSON="$(curl -sS -X POST "http://$NOETL_HOST:$NOETL_PORT/api/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "tests/fixtures/playbooks/batch_execution/heavy_payload_pipeline_in_step_parallel",
    "payload": {
      "execution_mode": "direct_stress",
      "seed_rows": 220,
      "payload_kb_per_item": 256,
      "details_api_url": "https://httpbin.org/anything/heavy-item-detail"
    }
  }')"

echo "$RUN_JSON" | jq .
export EXECUTION_ID="$(echo "$RUN_JSON" | jq -r '.execution_id')"
echo "EXECUTION_ID=$EXECUTION_ID"
```

## Validation queries

Execution summary from final step:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT result
   FROM noetl.event
   WHERE execution_id = $EXECUTION_ID
     AND event_type = 'step.exit'
     AND node_name = 'summarize'
   ORDER BY event_id DESC
   LIMIT 1;" \
  --schema noetl --format json
```

Row-level completeness and byte profile:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT
     COUNT(*) AS stored_rows,
     COUNT(*) FILTER (WHERE http_status = 200) AS ok_rows,
     MIN(item_id) AS min_item_id,
     MAX(item_id) AS max_item_id,
     AVG(request_bytes)::bigint AS avg_request_bytes,
     AVG(response_bytes)::bigint AS avg_response_bytes
   FROM public.heavy_payload_results
   WHERE execution_id = '$EXECUTION_ID';" \
  --schema public --format table
```

Missing rows check:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT COUNT(*) AS missing_rows
   FROM public.heavy_payload_source src
   LEFT JOIN public.heavy_payload_results tgt
     ON src.execution_id = tgt.execution_id
    AND src.item_id = tgt.item_id
   WHERE src.execution_id = '$EXECUTION_ID'
     AND tgt.item_id IS NULL;" \
  --schema public --format table
```

Event trace around failures/retries:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT event_id, event_type, node_name, status, error, created_at
   FROM noetl.event
   WHERE execution_id = $EXECUTION_ID
   ORDER BY event_id DESC
   LIMIT 120;" \
  --schema noetl --format table
```

## GKE runtime observation commands

Watch pod CPU/memory while stress run is active:

```bash
kubectl -n noetl top pod
```

Check server and worker logs for retries/failures:

```bash
kubectl -n noetl logs deploy/noetl --tail=200
kubectl -n noetl logs deploy/noetl-worker --tail=200
```

## Resource control guidance

Use these controls to keep streaming batch runs stable:

1. Prefer `chunked_optimal` for production runs.
2. Keep `batch_size` bounded (for example 20-60 for 200-300 KB payloads).
3. Keep parent chunk-worker parallelism bounded (`max_in_flight: 3` in this fixture).
4. Keep worker loop `max_in_flight` moderate (`15` in chunk worker by default).
5. Keep large results reference-first (default `NOETL_INLINE_MAX_BYTES=65536`).
6. Tune HTTP pool reuse if needed:
   - `NOETL_HTTP_MAX_CONNECTIONS`
   - `NOETL_HTTP_MAX_KEEPALIVE_CONNECTIONS`
   - `NOETL_HTTP_KEEPALIVE_EXPIRY_SECONDS`
7. If a run stalls around ~100 items, compare `direct_stress` vs `chunked_optimal` on identical payload size and inspect:
   - retries per node,
   - missing terminal events,
   - pod memory growth,
   - max persisted `item_id` in `heavy_payload_results`.

## Cleanup for one execution (optional)

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "DELETE FROM public.heavy_payload_results WHERE execution_id = '$EXECUTION_ID';
   DELETE FROM public.heavy_payload_source WHERE execution_id = '$EXECUTION_ID';" \
  --schema public --format table
```
