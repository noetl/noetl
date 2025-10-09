# Test Plan for Control Loop Refactor

This plan outlines unit, integration, and end-to-end tests to validate the refactored control loop and MCP schema support.

1) Unit tests
- EventService
  - Valid status enforced; invalid rejected with clear error.
  - catalog_id fallback to earliest event when metadata/context absent.
  - Dedupe guards for step_started and loop_iteration (no duplicate inserts).
- Broker
  - Initial dispatch finds first actionable step and enqueues once (idempotent across retries).
  - Iterator expansion: correct number of queue items; loop_iteration markers emitted.
  - Non-loop advancement: step_completed emission when action_completed appears.
- Queue API
  - enqueue with string execution_id → stored as bigint; list/lease/complete happy paths.
  - complete triggers broker reevaluation and (when applicable) parent reevaluation.
- Worker
  - Uses server-rendered task; does not double-merge payloads.
  - Emits start/complete events with lineage when parent_event_id present.

2) Integration tests (DB-backed)
- Basic playbook: start → first step → next step → end ⇒ execution_complete once; correct events and queue states.
- Iterator playbook: per-item jobs created; per-iteration results mapped; final aggregation event emitted; broker advances.
- Nested playbook: parent tracks child via parent_execution_id; results propagated back; control loop continues.
- Save semantics: save at step and end persists according to docs/save_result.md; verify storage side-effects where possible (or mock).

3) MCP schema tests
- Validate mcp section references (models/tools/resources/prompts/turns) resolve; invalid names error out with helpful messages.
- Compile mcp.turns into concrete workflow steps; enqueue/lease/execute path produces expected events.
- Tool/resource integration test: resource-driven prompt with a tool_allowed branch executed serially.

4) Idempotency and concurrency tests
- Duplicate step_started and loop_iteration insert attempts are prevented by DB constraints and app-level guards.
- Racing enqueue attempts for the same (execution_id,node_id) result in a single queue row.

5) Observability tests (log/metrics presence)
- Key logs emitted during iterator expansion, aggregation, and broker triggers contain execution_id, step_name, current_index, counts.

Fixtures and utilities
- Reuse tests/fixtures/playbooks/* and tests/fixtures/payloads/*.
- Add MCP example playbooks under tests/fixtures/playbooks/mcp/*.

CI considerations
- Mark DB integration tests; allow running a subset for quick validation.
- Provide docker-compose for PG if not already present, or use testcontainer.
