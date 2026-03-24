# BHS State Report Synthetic Load Test

This fixture is a synthetic, production-shaped load test for the BHS state-report workflow.

## Goals

1. Keep the step names and execution shape close to `bhs/state_report_generation_prod_v10`.
2. Use only synthetic data so the fixture is safe to run in test environments.
3. Exercise wide execution context, distributed batch workers, result externalization, and event churn under realistic names.
4. Provide a repeatable load-test playbook under the canonical `tests/fixtures/playbooks/load_test/` area.

## Playbooks

- Main fixture: `tests/fixtures/playbooks/load_test/bhs_state_report_synthetic_load/bhs_state_report_synthetic_load.yaml`
- Worker fixture: `tests/fixtures/playbooks/load_test/bhs_state_report_synthetic_load/bhs_state_report_synthetic_load_worker.yaml`

## What It Simulates

- facility preflight and facility selection
- Athena dataview fetch + parse
- patient id extraction and context loading
- patient fan-out for demographics, assessments, medications, conditions, and ADT
- distributed batch worker execution for synthetic patient work items

## Default Load Shape

- `total_items: 540`
- `batch_size: 30`
- `concurrent_batches: 1`
- `items_max_in_flight: 1`

These defaults are intentionally close to the medication-path scale we have been validating in prod, while still being safe to raise for heavier stress runs.

## Example

Register:

```bash
curl -X POST http://localhost:8082/api/catalog/register \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/playbooks/load_test/bhs_state_report_synthetic_load/bhs_state_report_synthetic_load.yaml
```

Execute:

```bash
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{"path":"load_test/bhs_state_report_synthetic_load"}'
```
