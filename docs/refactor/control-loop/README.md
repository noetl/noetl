# Control Loop Refactor Plan (Index)

This folder contains a structured, step-by-step plan to refactor the playbook execution control loop and extend the Playbook YAML schema to support MCP (Model Context Protocol) constructs. Follow the documents in order.

Documents
1. 1-overview-and-scope.md — Goals, non-goals, drivers, success criteria.
2. 2-current-architecture.md — Inventory of modules, data flows, DB tables, and current lifecycle.
3. 3-target-architecture.md — Desired state machine, module responsibilities, data contracts, and semantics.
4. 4-migration-strategy.md — Phased rollout, feature flags, migrations, and rollback.
5. 5-mcp-schema-extension.md — YAML schema additions for MCP (models/tools/resources/prompts/turns) and execution mapping.
6. 6-test-plan.md — Unit/integration/e2e test scenarios covering iterator/nested playbooks and MCP.
7. 7-issue-breakdown.md — GitHub-ready tasks with acceptance criteria and references.
8. 8-checklists.md — Implementation and verification checklists.

How to use this plan
- Read 1 → 3 to understand the architectural changes and contracts.
- Schedule and execute 4 (migration) with DB constraints first to establish idempotency.
- Implement issues in 7 in the recommended order, using 8 as your tracking checklist.
- Use 6 to guide test additions as you implement each milestone.
- For MCP features, start with 5 to update schema and provide examples; integrate gradually.

Examples
- docs/refactor/control-loop/examples/00-simple-playbook-v2.yaml — Minimal v2 playbook (start → python step → end).
- docs/refactor/control-loop/examples/01-iterator-playbook-v2.yaml — Iterator step (type: iterator) with inner executable action using tool: http; demonstrates per-item saves and event flow.
- docs/refactor/control-loop/examples/README.md — How the examples exercise the refactor and expected results.

Related documentation
- docs/system_control_loop_communication_protocol.md — Current end-to-end flow and issues.
- docs/communication-algorithm.md — Communication algorithm and historical notes.
- docs/save_result.md — Canonical result envelope and save semantics.

Notes
- This refactor is NOT backward compatible. It introduces a clean v2 with deliberate breaking changes and precise contracts.
- MCP support is first-class in the new schema. Legacy step types may require migration or be removed.
- v2 playbooks MUST include:
  - metadata.path and metadata.name (mandatory) for catalog linkage and identification.
  - a workload section (static variables) which can be overridden by transition/payload data.
  - a workbook section as a list of named actions; workflow steps reference them via `type: workbook` and `task: <action_name>`.
