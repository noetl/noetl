# traveler_batch_enrichment_in_step

This fixture demonstrates **bounded batched enrichment** with a parent playbook + batch worker playbook:

1. Parent seeds source rows and builds 20 batch windows (`batch_size=100`, `max_batches=20`)
2. Parent runs one worker-playbook execution per batch window and waits for completion (`return_step: end`)
3. Worker queries its 100-row window (`OFFSET/LIMIT`)
4. Worker runs `kind: http` per traveler using `loop.spec.mode: parallel`
5. Worker validates/transforms responses and stores rows to target table
6. Parent validates total persisted output and summarizes

## Why this pattern

- Enforces fixed batch count and size (20 x 100 by default)
- Uses parallel HTTP processing inside each batch worker
- Preserves strict batch order (next 100 starts only after current 100 completes)
- Stores each traveler result with `batch_number` attribution
- Keeps parent orchestration simple and distributed-safe
- Uses `kind: http` task for traveler profile calls (no direct HTTP client calls inside Python code)

## Why not `kind: transfer` here

`transfer` is good for direct source→target movement with mapping/cursor/chunking, but this use case requires per-row HTTP enrichment and custom validation before insert. That logic is better represented as explicit pipeline tasks.

## Files

- Playbook: `tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/traveler_batch_enrichment_in_step.yaml`
- Worker: `tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_chunk_worker/traveler_batch_enrichment_chunk_worker.yaml`

## Run

This fixture is intended for **distributed runtime** (server + worker), not local runtime.

```bash
noetl register playbook --file tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step/traveler_batch_enrichment_in_step.yaml
noetl exec catalog://tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step -r distributed
```

Or dry-run validation only:

```bash
noetl exec catalog://tests/fixtures/playbooks/batch_execution/traveler_batch_enrichment_in_step -r distributed --dry-run
```

## Performance Notes

- `profile_api_url` points to a public endpoint by default. End-to-end time will scale with external network latency.
- For realistic throughput testing, use a low-latency in-cluster endpoint for `profile_api_url`.
- Default fixture scale is `seed_rows=2000`, `batch_size=100`, `max_batches=20` (20 rounds max).
- HTTP client keep-alive pooling can be tuned on workers:
  - `NOETL_HTTP_MAX_CONNECTIONS` (default `200`)
  - `NOETL_HTTP_MAX_KEEPALIVE_CONNECTIONS` (default `50`)
  - `NOETL_HTTP_KEEPALIVE_EXPIRY_SECONDS` (default `30`)
  - `NOETL_HTTP_ENABLE_HTTP2` (default `true`)
