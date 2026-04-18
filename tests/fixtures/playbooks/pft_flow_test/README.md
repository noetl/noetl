# PFT Flow Test Playbook

End-to-end integration test that reproduces the full patient-data fetch pipeline from
`state_report_generation_prod_v13`, without Snowflake. Designed to surface the
loop.done concurrent-dispatch race bug present in NoETL ≤ v2.14.7.

## Files

| File | Purpose |
|---|---|
| `test_pft_flow.yaml` | Main playbook — facility loop, patient batching, 5 fetch steps, MDS batching, validation |
| `test_mds_batch_worker.yaml` | Sub-playbook — fetches MDS assessment details for one OFFSET/LIMIT slice |
| `pft_queue_db_maintenance.yaml` | Optional one-time queue maintenance for an already-used `demo_noetl` database |

## What it tests

The critical code path: DB-based patient batching using a `NOT EXISTS` + `INSERT RETURNING LIMIT 100`
CTE that atomically claims patients into `pft_test_patient_fetch_status` (tombstones). When the
loop.done race fires prematurely, subsequent batches have tombstones inserted but their fetch loop
is never started — patients are silently lost.

Pass criterion: every facility shows `1000/1000` patients in all five result tables.
Any shortfall means the race bug is still present.

## Test parameters

| Parameter | Value |
|---|---|
| Facilities | 10 |
| Patients per facility | 1 000 |
| Total patients | 10 000 |
| Batch size (patients) | 100 (LIMIT 100 per CTE claim) |
| Batches per facility per data type | 10 |
| Page size (API) | 10 records/page |

## Data flow

```
start
  └─ load_next_facility                    # pick lowest active facility
       └─ setup_facility_work              # TRUNCATE work, DELETE tombstones, seed 1000 patients
            └─ load_patients_for_assessments  ──┐
                 ├─ fetch_assessments ──(loop.done)─┘   # paginated 2-4 pages
                 └─ load_patients_for_conditions    ──┐
                      ├─ fetch_conditions ──(loop.done)─┘  # paginated 1-3 pages
                      └─ load_patients_for_medications ──┐
                           ├─ fetch_medications ──(loop.done)─┘  # paginated 2-3 pages
                           └─ load_patients_for_vital_signs ──┐
                                ├─ fetch_vital_signs ──(loop.done)─┘  # always 1 page
                                └─ load_patients_for_demographics ──┐
                                     ├─ fetch_demographics ──(loop.done)─┘  # non-paginated
                                     └─ count_mds_assessments
                                          └─ prepare_mds_work
                                               └─ build_mds_batch_plan
                                                    └─ run_mds_batch_workers  # sub-playbook loop
                                                         └─ validate_facility_results
                                                              └─ log_facility_validation
                                                                   └─ mark_facility_processed
                                                                        ├─ load_next_facility  (more facilities)
                                                                        └─ validate_all_results (done)
                                                                             └─ check_results
                                                                                  └─ end
```

## Fetch step pattern

Each `fetch_*` step runs a `task_sequence` loop over the claimed patient batch.
On `loop.done` it routes back to the corresponding `load_patients_for_*` step,
which either claims the next batch (row_count > 0 → fetch again) or exits the
data-type chain (row_count == 0 → next data type).

The loopback arc uses `when: '{{ event.name == "loop.done" }}'` — this is the fix
for the v2.14.7 bug where every `call.done` evaluated the arc and `mode: exclusive`
silently dropped all but the first dispatch.

## Validation

`validate_facility_results` counts `DISTINCT pcc_patient_id` from each **result table**
(not tombstones) and `COUNT(*)` from `pft_test_patient_fetch_status` for comparison:

```sql
SELECT
  COUNT(DISTINCT pcc_patient_id) FROM pft_test_patient_assessments  -- actual data
  ...
  COUNT(DISTINCT pcc_patient_id) FROM pft_test_patient_fetch_status -- tombstones
WHERE facility_mapping_id = N AND data_type = 'assessments';
```

On a buggy engine: `tombstones = 1000`, `assessments_done = 100–200` (one or two batches only).
On a fixed engine: both equal `1000`.

Results are written to `pft_test_validation_log` and asserted in `check_results`.

## Infrastructure requirements

- **NoETL server** ≥ v2.14.8 (for `try_claim_loop_done` CAS fix)
- **PostgreSQL** via `pg_k8s` credential (`postgres.postgres.svc.cluster.local:5432`, database `demo_noetl`)
- **Test API server** (`paginated-api` deployment in `test-server` namespace, port 5555)
  — serves deterministic per-patient responses for all 7 endpoints used by the fetch steps

## Running the test

Register and execute via the HTTP API (the NoETL CLI ≤ v2.13.0 cannot parse multi-tool loop steps):

```bash
# Register (bump version each time the playbook changes)
curl -X POST http://localhost:8082/api/catalog \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/playbooks/pft_flow_test/test_pft_flow.yaml

# Execute
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/fixtures/playbooks/pft_flow_test/test_pft_flow", "version": <N>}'
```

Check results after completion:

```sql
SELECT facility_mapping_id, assessments_done, conditions_done, medications_done,
       vital_signs_done, demographics_done, total_expected, tombstones_assessments
FROM public.pft_test_validation_log
WHERE execution_id = '<execution_id>'
ORDER BY facility_mapping_id;
```

## Optional queue maintenance

If the demo database has already seen a long-running or cancelled PFT workload and
you want to clean up queue-table bloat before the next benchmark slice, run the
companion maintenance playbook first. It uses Python + `psycopg` with autocommit,
so it can safely execute `CREATE INDEX CONCURRENTLY` and `VACUUM`, which are not a
good fit for the main reset-heavy fixture setup step.

```bash
curl -X POST http://localhost:8082/api/catalog \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/playbooks/pft_flow_test/pft_queue_db_maintenance.yaml

curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/fixtures/playbooks/pft_flow_test/pft_queue_db_maintenance", "version": <N>}'
```

## MDS sub-playbook

`test_mds_batch_worker` is invoked once per OFFSET/LIMIT slice of `pft_test_mds_assessment_ids_work`.
It fetches assessment details from `/api/v1/mds/assessment/{id}` and upserts into
`pft_test_mds_assessment_details`. Called with `max_in_flight: 1` from the parent to keep
concurrency predictable during testing.
