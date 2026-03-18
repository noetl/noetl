# Reference Chain Loop Stress Test (Neutral)

This fixture validates long-running pagination + loop processing with bounded reference metadata.

## What It Tests

1. Pagination over a large neutral dataset (`total_records` default: `382`).
2. Linked reference mode (`ref_mode=linked`) where only nearest refs are carried forward.
3. Loop processing for every collected record with bounded per-record validation.
4. Completion under load without loop-progress stalls.

## Components

- API fixture endpoint:
  - `GET /api/v1/reference-chain/items`
- Playbook:
  - `tests/fixtures/playbooks/load_test/reference_chain_loop_stress/reference_chain_loop_stress.yaml`
- Runner script:
  - `tests/scripts/test_reference_chain_loop_stress.py`

## Run on kind-noetl

1. Rebuild and roll out the test-server image:

```bash
docker build -t local/test-server:latest -f docker/test-server/Dockerfile .
kind load docker-image local/test-server:latest --name noetl
kubectl apply -f ci/manifests/test-server/namespace.yaml -f ci/manifests/test-server/deployment.yaml
kubectl -n test-server rollout restart deploy/paginated-api
kubectl -n test-server rollout status deploy/paginated-api
```

2. Run the end-to-end stress test:

```bash
python tests/scripts/test_reference_chain_loop_stress.py \
  --base-url http://localhost:30082 \
  --total-records 382 \
  --page-size 25 \
  --stall-seconds 180 \
  --timeout 1200
```

## Expected Result

- Execution status: `completed`
- Finalize step result status: `ok`
- Loop stats total equals configured `total_records`
- No stall condition reported by the runner
