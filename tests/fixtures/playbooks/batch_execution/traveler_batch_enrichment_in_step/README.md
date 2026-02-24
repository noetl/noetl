# traveler_batch_enrichment_in_step

This fixture validates a full batched enrichment pattern:

1. Parent playbook seeds traveler source rows.
2. Parent creates fixed batch windows.
3. Parent runs one worker playbook per batch window.
4. Worker fetches one batch (`OFFSET/LIMIT`), runs parallel HTTP (`loop.spec.mode: parallel`), transforms, and persists.
5. Parent waits on `loop.done`, validates persisted rows, and returns a summary.

## What this test is for

- Parent loop orchestration over child playbook calls (`kind: playbook`).
- Parallel HTTP execution inside each worker batch.
- Correct aggregation/continuation behavior for `loop.done`.
- End-to-end row persistence and data completeness checks.

## Fixture files

- Parent playbook:
  `tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/traveler_batch_enrichment_in_step.yaml`
- Worker playbook:
  `tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_chunk_worker/traveler_batch_enrichment_chunk_worker.yaml`

## Prerequisites

- NoETL server + worker are running (distributed runtime).
- A usable Postgres credential exists for `pg_auth` (default: `pg_k8s` in this fixture).
- You can reach the NoETL API (either direct host/port or `kubectl port-forward`).
- Tools: `noetl`, `kubectl`, `jq`.

If NoETL API is only internal, start a port-forward in a separate terminal:

```bash
kubectl -n noetl port-forward svc/noetl 8082:8082
```

All commands below assume:

```bash
NOETL_HOST=localhost
NOETL_PORT=8082
```

## Register both playbooks

Register worker first, then parent:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" catalog register \
  tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_chunk_worker/traveler_batch_enrichment_chunk_worker.yaml

noetl --host "$NOETL_HOST" --port "$NOETL_PORT" catalog register \
  tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/traveler_batch_enrichment_in_step.yaml
```

## Dry-run validation

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" exec \
  catalog://tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step \
  -r distributed \
  --dry-run
```

## Smoke test (recommended first)

Use smaller workload for fast verification:

- `seed_rows=200`
- `batch_size=50`
- `max_batches=4`
- expected processed rows = `LEAST(200, 50*4) = 200`

### Smoke test quick commands (copy/paste)

```bash
export NOETL_HOST=localhost
export NOETL_PORT=8082

# Terminal A: expose NoETL API locally
kubectl -n noetl port-forward svc/noetl 8082:8082
```

```bash
# Terminal B: register worker + parent playbooks
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" catalog register \
  tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_chunk_worker/traveler_batch_enrichment_chunk_worker.yaml

noetl --host "$NOETL_HOST" --port "$NOETL_PORT" catalog register \
  tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/traveler_batch_enrichment_in_step.yaml
```

```bash
# Terminal B: run smoke workload and capture execution id
RUN_JSON="$(curl -sS -X POST "http://$NOETL_HOST:$NOETL_PORT/api/execute" \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step",
    "payload": {
      "seed_rows": 200,
      "batch_size": 50,
      "max_batches": 4,
      "profile_api_url": "https://httpbin.org/anything/traveler-profile"
    }
  }')"

echo "$RUN_JSON" | jq .
export EXECUTION_ID="$(echo "$RUN_JSON" | jq -r '.execution_id')"
echo "EXECUTION_ID=$EXECUTION_ID"
```

```bash
# Terminal B: wait until execution completes or fails
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

Optional event tail:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT event_id, event_type, node_name, status, created_at
   FROM noetl.event
   WHERE execution_id = $EXECUTION_ID
   ORDER BY event_id DESC
   LIMIT 40;" \
  --schema noetl --format table
```

## Data validation SQL

### 1) Validate persisted counts

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT
     COUNT(*) AS stored_rows,
     COUNT(*) FILTER (WHERE profile_status = 200) AS successful_http_calls,
     COUNT(*) FILTER (WHERE is_valid = TRUE) AS valid_rows,
     COUNT(*) FILTER (WHERE is_valid = FALSE) AS invalid_rows,
     COUNT(DISTINCT batch_number) AS batches_with_rows,
     MAX(batch_number) AS max_batch_number
   FROM public.traveler_batch_results
   WHERE execution_id = '$EXECUTION_ID';" \
  --schema public --format table
```

Expected for smoke test:

- `stored_rows = 200`
- `max_batch_number <= 4`
- `invalid_rows = 0` (normally)

### 2) Validate no missing rows in expected range

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT COUNT(*) AS missing_rows
   FROM public.traveler_batch_source src
   LEFT JOIN public.traveler_batch_results tgt
     ON src.execution_id = tgt.execution_id
    AND src.traveler_id = tgt.traveler_id
   WHERE src.execution_id = '$EXECUTION_ID'
     AND src.traveler_id <= LEAST(200, 50 * 4)
     AND tgt.traveler_id IS NULL;" \
  --schema public --format table
```

Expected: `missing_rows = 0`

### 3) Validate parent transitioned after loop (loop completion path)

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT COUNT(*) AS validate_step_enters
   FROM noetl.event
   WHERE execution_id = $EXECUTION_ID
     AND event_type = 'step.enter'
     AND node_name = 'validate_persisted_results';" \
  --schema noetl --format table
```

Expected: `validate_step_enters = 1`

### 4) Validate summarize output payload

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "SELECT result
   FROM noetl.event
   WHERE execution_id = $EXECUTION_ID
     AND node_name = 'summarize'
     AND event_type = 'step.exit'
   ORDER BY event_id DESC
   LIMIT 1;" \
  --schema noetl --format json
```

Check fields in `result`:

- `status = completed`
- `execution.batch_worker_iterations` matches expected batch rounds
- `data.expected_rows` and `data.stored_rows` are equal
- `data.missing_rows = 0`

## Full-scale run (fixture defaults)

Default profile in the playbook:

- `seed_rows=2000`
- `batch_size=100`
- `max_batches=20`
- expected processed rows = `LEAST(2000, 100*20) = 2000`

Run:

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" exec \
  catalog://tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step \
  -r distributed
```

For this run, use the same validation queries as above, replacing expected range with:

```sql
LEAST(2000, 100 * 20)
```

## Cleanup for one execution (optional)

```bash
noetl --host "$NOETL_HOST" --port "$NOETL_PORT" query \
  "DELETE FROM public.traveler_batch_results WHERE execution_id = '$EXECUTION_ID';
   DELETE FROM public.traveler_batch_source WHERE execution_id = '$EXECUTION_ID';" \
  --schema public --format table
```

## Troubleshooting

- `Connection refused` on `localhost:8082`:
  - Start `kubectl -n noetl port-forward svc/noetl 8082:8082`
  - Or use reachable `--host/--port`.
- `Credential not found` (`pg_k8s`):
  - Provide `--set pg_auth=<your_credential_name>`
  - Or register/update the expected credential.
- High latency/timeouts to external HTTP endpoint:
  - Override `profile_api_url` with low-latency endpoint.
- Fewer rows than expected:
  - Check `summarize.result.data.missing_rows`
  - Check recent `step.exit` and `call.error` events for worker steps.

## Performance notes

- `profile_api_url` defaults to a public endpoint. Throughput is network-bound.
- Worker HTTP parallelism is controlled by `loop.spec.max_in_flight` in worker playbook (`25` by default).
- HTTP pooling knobs (worker env):
  - `NOETL_HTTP_MAX_CONNECTIONS` (default `200`)
  - `NOETL_HTTP_MAX_KEEPALIVE_CONNECTIONS` (default `50`)
  - `NOETL_HTTP_KEEPALIVE_EXPIRY_SECONDS` (default `30`)
  - `NOETL_HTTP_ENABLE_HTTP2` (default `true`)
