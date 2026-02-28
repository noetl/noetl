*[noetlctl-context-switching][~/projects/noetl/noetl]$ cargo build -p noetl
   Compiling rpassword v3.0.2
   Compiling noetl v2.8.6 (/Volumes/X10/projects/noetl/noetl/crates/noetl)
    Finished `dev` profile [unoptimized + debuginfo] target(s) in 9.53s
*[noetlctl-context-switching][~/projects/noetl/noetl]$ cp ./target/debug/noetl bin/                                          
*[noetlctl-context-switching][~/projects/noetl/noetl]$ cp ./target/debug/noetl .venv/bin/
*[noetlctl-context-switching][~/projects/noetl/noetl]$ which noetl                     
/Users/akuksin/projects/noetl/noetl/.venv/bin/noetl
*[noetlctl-context-switching][~/projects/noetl/noetl]$ ./target/debug/noetl register playbook --file tests/fixtures/playbooks/batch_execution/server_oom_stress_chunk_worker/server_oom_stress_chunk_worker.yaml
Playbook registered successfully: {"catalog_id":"572403900846703437","kind":"Playbook","message":"Resource 'tests/fixtures/playbooks/batch_execution/server_oom_stress_chunk_worker' version '10' registered.","path":"tests/fixtures/playbooks/batch_execution/server_oom_stress_chunk_worker","status":"success","version":10}
*[noetlctl-context-switching][~/projects/noetl/noetl]$ ./target/debug/noetl register playbook --file tests/fixtures/playbooks/batch_execution/server_oom_stress_test/server_oom_stress_test.yaml
Playbook registered successfully: {"catalog_id":"572403990730637390","kind":"Playbook","message":"Resource 'tests/fixtures/playbooks/batch_execution/server_oom_stress_test' version '41' registered.","path":"tests/fixtures/playbooks/batch_execution/server_oom_stress_test","status":"success","version":41}
*[noetlctl-context-switching][~/projects/noetl/noetl]$ ./target/debug/noetl exec catalog://tests/fixtures/playbooks/batch_execution/server_oom_stress_test --runtime distributed --payload '{"total_items":200,"batch_size":40,"concurrent_batches":1,"items_max_in_flight":1}'


Executing playbook on distributed server...
  Path: tests/fixtures/playbooks/batch_execution/server_oom_stress_test
  Server: https://gateway.mestumre.dev

Execution started:
{
  "commands_generated": 1,
  "execution_id": "572404124981919948",
  "status": "started"
}

To check status:
  noetl execute status "572404124981919948"



*[noetlctl-context-switching][~/projects/noetl/noetl]$ noetl execute status "572404124981919948"

============================================================
Execution: 572404124981919948
Status:    RUNNING
Steps:     24 completed
Current:   build_batch_plan

Completed steps:
  - ctx_step_19
  - ctx_step_13
  - ctx_step_02
  - ctx_step_21
  - ctx_step_14
  - ctx_step_05
  - ctx_step_20
  - ctx_step_01
  - ctx_step_09
  - ctx_step_18
  - ctx_step_03
  - setup_test_data
  - ctx_step_12
  - ctx_step_16
  - ctx_step_17
  - ctx_step_08
  - ctx_step_06
  - ctx_step_11
  - ctx_step_04
  - ctx_step_10
  - ctx_step_07
  - build_batch_plan
  - start
  - ctx_step_15
============================================================

Use --json for full execution details
*[noetlctl-context-switching][~/projects/noetl/noetl]$ noetl execute status 572404124981919948 --json | jq '{total_items:.variables.total_items,batch_size:.variables.batch_size,batch_count:.variables.build_batch_plan.batch_count,concurrent_batches:.variables.concurrent_batches,items_max_in_flight:.variables.items_max_in_flight}'

{
  "total_items": 200,
  "batch_size": 40,
  "batch_count": 5,
  "concurrent_batches": 1,
  "items_max_in_flight": 1
}




SELECT pg_typeof(result_data) AS result_data_type
FROM public.stress_test_results
LIMIT 1;

ROLLBACK;

SELECT
  item_id,
  (result_data ? 'payload') AS has_payload,
  left(result_data->>'payload', 60) AS payload_preview,
  ((result_data->'data'->>'field_000') IS NOT NULL) AS has_field_000,
  ((result_data->'data'->>'field_599') IS NOT NULL) AS has_field_599,
  (SELECT COUNT(*) FROM json_object_keys((result_data->'data')::json)) AS data_fields
FROM public.stress_test_results
ORDER BY item_id DESC
LIMIT 5;