# Control Loop v2 Example Playbooks

This folder contains minimal playbooks used to validate the refactored control loop. These examples are intentionally small and deterministic so you can step through enqueue → lease → execute → emit → complete and observe the resulting events and queue records.

Notes
- These examples target v2 of the control loop and are NOT backward compatible with any legacy schemas.
- The examples are designed to highlight refactoring goals: clear router start, actionable steps, canonical result envelopes, and a deterministic final result.

Files
- 00-simple-playbook-v2.yaml — Start → python step → end with a result mapping. Shows transition payload overlay (router passing a city) and save semantics.

How this exercises the refactor
1) After execution_started, the broker finds `start`, routes to `evaluate_temp`, emits `step_started`, and enqueues the job.
2) The worker leases the job, renders the task on the server, runs the inline python plugin, and emits `action_completed` with the required envelope.
3) The queue item is marked complete; broker emits `step_completed` and finalizes the `end` step by emitting an `execution_complete` with the mapped result.

Expected final result
```json
{
  "status": "COMPLETED",
  "data": {
    "summary": "Temperature in Prague is 21C",
    "city": "Prague",
    "temp_c": 21
  }
}
```

Next steps
- Use this example in integration tests to validate: first step dispatch, worker execution, event persistence, and broker advancement.
- Extend with an iterator example (fan-out loop) when testing loop aggregation.
