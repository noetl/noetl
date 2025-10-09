# Issue Breakdown (GitHub-Ready)

Each task includes: Title, Problem, Proposed Solution, Acceptance Criteria, References, Labels, Effort, Priority, and Dependencies.

1) Refactor: Normalize execution_id usage across control loop
- Problem: String vs bigint inconsistencies cause failures.
- Proposed: Ensure normalize_execution_id_for_db used at all DB boundaries; audit broker and queue paths.
- Acceptance: All SQL touching event/queue uses bigint; roundtrip test with string execution_id passes.
- References: queue.py (helper, enqueue), broker.py (queue inserts), broker/service.py (enqueue agg job).
- Labels: area:queue, reliability, tech-debt | Effort: S | Priority: High

2) DB-level idempotency for marker events
- Problem: Duplicate step_started/loop_iteration events.
- Proposed: Add UNIQUE partial indexes; handle IntegrityError as no-op.
- Acceptance: Duplicates not inserted; emit() stable under retries.
- References: event/service.py (dedupe guards).
- Labels: area:event, db, idempotency | Effort: M | Priority: High

3) Lineage propagation (parent_event_id)
- Problem: Missing lineage breaks aggregation and mapping.
- Proposed: Ensure trigger_event_id propagates to ctx._meta.parent_event_id (non-loop & loop); worker echoes; controllers preserve.
- Acceptance: loop_iteration and action_* events carry correct parent_event_id; integration test passes.
- References: event/service.py (route trigger), broker.py (ctx meta), worker.py (emit lineage).
- Labels: area:broker, lineage | Effort: M | Priority: High

4) Catalog_id fallback in EventService.emit
- Problem: Events fail when path/version missing.
- Proposed: Fallback to earliest event’s catalog_id; warn.
- Acceptance: Events accepted when execution already has a catalog; unit test included.
- References: event/service.py (catalog resolution).
- Labels: area:event, resiliency | Effort: S | Priority: High

5) Canonical payload overlay and render
- Problem: Divergent merging between server and worker.
- Proposed: Server authoritative render; worker uses rendered task; document precedence.
- Acceptance: Tests confirm final task equals server render; plugins read from context.work.input.
- References: broker.py (transition merge), worker.py (use rendered_task).
- Labels: area:dsl, consistency | Effort: M | Priority: Medium

6) Broker trigger broadening for loop/result lifecycle
- Problem: Parent workflow stalls sometimes.
- Proposed: Include loop_completed and result with loop metadata as fast-path triggers; parent evaluation when applicable.
- Acceptance: Iterator playbooks complete without manual nudges; tests.
- References: event/service.py (fast-path set), broker/service.py.
- Labels: area:broker, scheduling | Effort: S | Priority: Medium

7) Snapshot updates formalization
- Problem: Snapshots (transition/workbook/workload/workflow) updates are implicit.
- Proposed: Define per-event update rules; implement in EventService or dedicated projector.
- Acceptance: Snapshots reflect current state across lifecycle; tests for projections.
- References: event/service.py, processing/workflow.py.
- Labels: area:event, projections | Effort: M | Priority: Medium

8) DB constraints for queue idempotency
- Problem: Duplicate queue items.
- Proposed: UNIQUE(execution_id,node_id); rely on ON CONFLICT DO NOTHING.
- Acceptance: Racing enqueues collapse to one row; test simulating race.
- References: broker.py, queue.py.
- Labels: db, idempotency | Effort: S | Priority: High

9) MCP schema support (docs + validation + examples)
- Problem: Playbook YAML lacks MCP constructs.
- Proposed: Add mcp section; implement validation; translate to steps.
- Acceptance: Example mcp playbook runs end-to-end; clear errors for unresolved refs.
- References: 5-mcp-schema-extension.md; schema validation layer.
- Labels: dsl, mcp, docs | Effort: M | Priority: Medium

10) Observability improvements
- Problem: Hard to debug loop aggregation timing/data.
- Proposed: Structured logs and counters at key points.
- Acceptance: Logs include execution_id/step/current_index/counts; visible in tests.
- References: broker.py (loop paths), queue.py (completion), broker/service.py.
- Labels: observability | Effort: S | Priority: Medium

Dependencies:
- (2) depends on DB migration readiness.
- (3) depends on (1) and partial changes in broker.
- (5) after (1); coordinate with (9).
- (6) optional but complements (3).
