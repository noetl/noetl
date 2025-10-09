# Control Loop Refactor: Overview and Scope

Goal: Refactor the playbook execution control loop into a clear, modular, and testable architecture that is easy to reason about and extend. Align the Playbook YAML schema to support the Model Context Protocol (MCP) concepts at the schema level (without depending on an SDK runtime).

Scope highlights:
- Clarify responsibilities and boundaries between Server (broker, event service, queue API) and Worker (execution, plugin invocation).
- Formalize event lifecycle and snapshot tables (transition, workbook, workload, workflow) updates.
- Enforce idempotency, lineage, and catalog linkage.
- Support iterator steps, nested playbooks, and save semantics consistently.
- Extend Playbook YAML to support MCP concepts (tools/resources/model/turns) and map them to existing execution primitives.

Non-goals (for this refactor):
- Rewriting plugin implementations (http/python/duckdb/postgres) beyond data/contract alignment.
- Introducing a new runtime other than the current Server/Worker deployment model.

Key drivers:
- Current loop is unstructured; implicit branching and scattered responsibilities hamper maintenance.
- Need to make the control loop progress deterministic, idempotent, and debuggable.
- Provide MCP-compliant schema so authors can describe LLM tool interactions declaratively.

Success criteria:
- A documented target architecture with a state machine and clear module responsibilities.
- A stepwise migration plan and issue breakdown to implement refactor incrementally.
- Updated YAML schema that validates MCP constructs and examples that run end-to-end.


## Baseline v2 Playbook Schema (required)

- metadata:
  - path: required (catalog resource path)
  - name: required (human-readable identifier)
- workload:
  - Static variables available to the execution context; may be overridden by transition/payload data during workflow progression.
- workbook:
  - A list of named actions. Each action has a unique name and a concrete type (python/http/duckdb/postgres/save/etc.).
  - Workflow steps reference these actions via `type: workbook` and `task: <action_name>`.
- workflow:
  - Must contain a `start` step (type: start) and an eventual `end` step (type: end). If a step has no explicit transition, it implicitly falls through to `end`.

See examples/00-simple-playbook-v2.yaml for a minimal reference.
