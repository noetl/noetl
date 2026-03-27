# fetch_load_test

Load test for NoETL fetch-step pagination under production-realistic conditions.

Validates that `max_in_flight: 5` on fetch steps holds under realistic load without worker crash or OOM — reproducing the structure of `fetch_medications` in `state_report_generation_prod_v10.yaml` that caused `CrashLoopBackOff` at `max_in_flight: 20`.

## What it tests

- **500 synthetic patients** processed in a parallel loop (`max_in_flight: 5`)
- **FHIR-like paginated responses** from the mock server (`/api/v1/patient-records`)
  - 2–5 pages per patient, deterministic per `patientId` (reproducible across runs)
  - ~100 KB per response page to trigger GCS externalization pressure
  - 2–4 second server-side delay to simulate real API latency
- **Assertion**: all 500 patients processed, final record count matches expected total
- **Go/no-go criterion**: playbook completes without worker crash or OOM kill

## Dependencies

Requires the mock server endpoint from **AHM-4287** to be deployed to the `test-server` namespace:

```
GET http://paginated-api.test-server.svc.cluster.local:5555/api/v1/patient-records
```

Verify the server is running:
```bash
curl http://localhost:30555/health
curl "http://localhost:30555/api/v1/patient-records?patientId=P-0001&page=1&pageSize=10" | jq '.meta'
```

## Running the test

```bash
# Standard run (max_in_flight: 5 — production readiness check)
noetl exec tests/fixtures/playbooks/pagination/fetch_load_test/test_fetch_load.yaml

# Override patient count for a quick smoke test
noetl exec tests/fixtures/playbooks/pagination/fetch_load_test/test_fetch_load.yaml \
  --var num_patients=20

# Reproduce the crash: increase max_in_flight to 20 in workload and run
# Expected: CrashLoopBackOff or OOM kill within the first few minutes
```

## Expected timing

| max_in_flight | Patients | Avg pages/patient | Avg delay/page | Estimated time |
|---------------|----------|-------------------|----------------|----------------|
| 5             | 500      | 3.5               | 3.0s           | ~17–20 min     |
| 5             | 500      | 3.5               | 0.1s *         | ~1–2 min       |
| 20            | 500      | 3.5               | 3.0s           | ~5–7 min †     |

\* Use `min_delay=0&max_delay=0.2` query params on the mock server (set via `PATIENT_RECORDS_MIN_DELAY` / `PATIENT_RECORDS_MAX_DELAY` env vars on the deployment) to speed up CI runs.

† At `max_in_flight: 20` the server's 50 req/s rate limit will be hit and 429 responses returned. The engine is expected to crash before completing due to GCS externalization pressure, not the rate limit itself.

## Server configuration (env vars)

These env vars can be set on the `paginated-api` Deployment to tune server behavior:

| Env var                        | Default | Description                            |
|--------------------------------|---------|----------------------------------------|
| `PATIENT_RECORDS_MIN_DELAY`    | `2.0`   | Minimum response delay (seconds)       |
| `PATIENT_RECORDS_MAX_DELAY`    | `4.0`   | Maximum response delay (seconds)       |
| `PATIENT_RECORDS_RATE_LIMIT`   | `50`    | Max requests per second (global)       |
| `PATIENT_RECORDS_MIN_PAGES`    | `2`     | Min pages per patient                  |
| `PATIENT_RECORDS_MAX_PAGES`    | `5`     | Max pages per patient                  |
| `PATIENT_RECORDS_PAYLOAD_KB`   | `100`   | Target response size per page (KB)     |

The delay, payload size, and rate limit parameters are also overridable per-request via lowercase query params (for example, `min_delay`, `max_delay`, `payload_kb`, `rate_limit`).

## Files

| File | Description |
|------|-------------|
| `test_fetch_load.yaml` | Main load test playbook |
| `README.md` | This file |

## Related

- **AHM-4287** — Mock server endpoint implementation
- **AHM-4288** — This load test playbook
- `tests/fixtures/servers/paginated_api.py` — Mock server source
- `state_report_generation_prod_v10.yaml` — Production playbook being validated
