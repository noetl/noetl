# Migration Strategy

This plan outlines phases to refactor the control loop with intentional breaking changes. Backward compatibility is not required; this is a clean v2 with precise, unambiguous contracts.

Phases:

Phase 0 — Baseline hardening
- Ensure bigint execution_id normalization across queue/event paths (recent patch). Verify all DB accesses use normalized IDs.
- Add additional logs and metrics around broker triggers and queue completion.

Phase 1 — DB idempotency and lineage
- Add UNIQUE constraints/indexes:
  - event: (execution_id, node_name) WHERE event_type = 'step_started'.
  - event: (execution_id, node_name, current_index) WHERE event_type = 'loop_iteration'.
  - queue: UNIQUE (execution_id, node_id).
- Update application logic to gracefully handle integrity errors as deduped no-ops.
- Guarantee parent_event_id propagation across enqueue paths.

Phase 2 — Payload canonicalization
- Define authoritative server-side rendering and final task config building.
- Worker switches to using rendered task only (fallback retained temporarily).
- Align envelope and save semantics; update plugin shims if needed.

Phase 3 — Snapshot updates and state machine
- Document and implement snapshot updates for transition, workbook, workload, workflow on each event type.
- Ensure execution_complete is emitted exactly once per execution.

Phase 4 — MCP schema support
- Introduce mcp section in Playbook YAML (tools/resources/models/turns) and map to execution primitives.
- Implement server-side validation and translation into tasks/steps.
- Provide examples and tests.

Phase 5 — Cleanup and deprecation
- Remove legacy payload aliases if acceptable (with, payload) after a deprecation window.
- Finalize docs and diagrams; ensure observability dashboards cover new flows.

Rollout considerations:
- Communicate clearly that this is a breaking v2; schedule DDL during maintenance windows.
- Provide migration guidance and scripts; remove compatibility shims.
- Enforce new validations and constraints by default (no feature flags required).

Rollback plan:
- Keep migrations reversible where possible; if rollback is needed, revert to pre-v2 schema and code.
- Compatibility code paths are intentionally removed; rollback means returning to the previous release.
