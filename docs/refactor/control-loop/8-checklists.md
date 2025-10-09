# Implementation and Verification Checklists

Implementation checklist
- [ ] Normalize execution_id at all DB boundaries (server & worker interactions).
- [ ] Add DB constraints: UNIQUE(event markers), UNIQUE(queue execution_id,node_id).
- [ ] Handle IntegrityError in emit() as dedup no-op for markers.
- [ ] Ensure parent_event_id propagates from trigger → queue ctx → worker → events.
- [ ] Canonical server-side render of task; worker uses rendered_task.
- [ ] Strengthen catalog_id fallback in EventService.emit.
- [ ] Expand broker triggers (loop_completed, result with loop metadata) and evaluate parent when applicable.
- [ ] Snapshot update projector for transition/workbook/workload/workflow.
- [ ] Add structured logs/metrics at iterator expansion and aggregation.
- [ ] MCP schema validation and translation to workflow.

Verification checklist
- [ ] Unit tests passing for EventService, broker, queue, worker components.
- [ ] Integration: basic playbook flow completes with correct events and snapshots.
- [ ] Integration: iterator flow aggregates correctly and advances.
- [ ] Integration: nested playbook propagates results back to parent.
- [ ] Idempotency: duplicate markers prevented; racing queue inserts collapse to one row.
- [ ] Observability: logs show execution_id, step_name, current_index, counts.
- [ ] MCP example playbook runs end-to-end and validates schema.
- [ ] Documentation cross-links validated; anchors resolve.
