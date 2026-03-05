# Async Batch Acceptance Contract (`/api/events/batch`)

`POST /api/events/batch` now uses an async acceptance flow:

1. Persist the incoming worker events plus a `batch.accepted` marker in `noetl.event`.
2. Enqueue background processing for engine routing + `command.issued` emission.
3. Return `202 Accepted` immediately with a `request_id`.

## Request headers

- `Idempotency-Key` (recommended): deduplicates retry submissions for the same `execution_id`.

## Response

```json
{
  "status": "accepted",
  "request_id": "5749...",
  "event_ids": [5749, 5750],
  "commands_generated": 0,
  "queue_depth": 3,
  "duplicate": false,
  "idempotency_key": "worker-1:..."
}
```

## Status tracking

- Polling: `GET /api/events/batch/{request_id}/status`
- SSE stream: `GET /api/events/batch/{request_id}/stream`

State transitions:

- `accepted` -> `processing` -> `completed`
- `accepted` -> `processing` -> `failed`

## Failure classes in error payloads

- `ack_timeout`: enqueue acknowledgement timed out
- `enqueue_error`: enqueue failed unexpectedly
- `queue_unavailable`: accept queue not available
- `worker_unavailable`: no background accept workers available
- `processing_timeout`: background processing exceeded timeout
- `processing_error`: background processing failed

## Environment variables

- `NOETL_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS` (default `0.25`)
- `NOETL_BATCH_ACCEPT_QUEUE_MAXSIZE` (default `1024`)
- `NOETL_BATCH_ACCEPT_WORKERS` (default `1`)
- `NOETL_BATCH_PROCESSING_TIMEOUT_SECONDS` (default `15.0`)
- `NOETL_BATCH_STATUS_STREAM_POLL_SECONDS` (default `0.5`)

## Metrics exposed at `/metrics`

- `noetl_batch_enqueue_latency_seconds_*`
- `noetl_batch_ack_timeout_total`
- `noetl_batch_queue_depth`
- `noetl_batch_first_worker_claim_latency_seconds_*`
