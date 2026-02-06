# HTTP tool (playbook authoring) — Canonical v10

This page previously documented legacy HTTP plugin shapes (`tool: http`, `endpoint`, `case`, `sink`).

Canonical v10 uses HTTP as a **tool task** (`kind: http`) inside `step.tool`, with:
- retry/polling/pagination via `task.spec.policy.rules`
- routing via `step.next.arcs[]`

## See also
- Canonical HTTP tool: `documentation/docs/reference/tools/http.md`
- Loop iteration: `documentation/docs/reference/iterator_v3.md`
- Retry: `documentation/docs/reference/retry_mechanism_v2.md`
