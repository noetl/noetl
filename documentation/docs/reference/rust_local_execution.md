# NoETL Rust Local Execution (Canonical v10)

This document describes the Rust implementation for **local mode** execution of **Canonical v10** playbooks.

Local mode is intended for development, testing, and CI/CD. Conceptually, the control-plane and data-plane run in a single process, but the **canonical semantics remain the same**.

## Quick start

```bash
# Execute a playbook in local mode
noetl exec ./playbook.yaml -r local

# With workload overrides
noetl exec ./playbook.yaml -r local --set key=value

# Target a specific step label (runtime-defined)
noetl exec ./playbook.yaml -r local --target my_step

# Dry-run (validate only)
noetl exec ./playbook.yaml -r local --dry-run
```

## Canonical v10 semantics (what local mode must preserve)

- **Step admission (server semantics):** `step.spec.policy.admit.rules`
- **Task execution (worker semantics):** `step.tool` pipeline; task outcome handling via `task.spec.policy.rules`
- **Routing (server semantics):** `step.next.spec` + `step.next.arcs[]` guarded by `when`
- **Loops:** `step.loop` (not a tool kind); per-iteration state lives in `iter.*`
- **One conditional keyword:** `when` (no legacy `eval`/`expr`/`case`)

Canonical references:
- `documentation/docs/reference/dsl/noetl_step_spec.md`
- `documentation/docs/reference/dsl/playbook_structure.md`
- `documentation/docs/reference/dsl/implement_agent_instructions.md`

## Deprecated legacy features (not canonical)

Local mode should not depend on legacy constructs such as:
- playbook-root `vars`
- step-level `retry:` wrappers
- `step.when`
- `next: [ ... ]` list routing

Use the canonical equivalents:
- `ctx` / `iter` via `set_ctx` / `set_iter` in task policy
- `task.spec.policy.rules`
- `step.spec.policy.admit.rules`
- `next.spec` + `next.arcs[]`

## Minimal canonical example

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: local_example
  path: examples/local_example

workload:
  api_url: "https://httpbin.org"

workflow:
  - step: start
    next:
      spec: { mode: exclusive }
      arcs:
        - step: call_api

  - step: call_api
    tool:
      - call:
          kind: http
          method: GET
          url: "{{ workload.api_url }}/get"
          spec:
            policy:
              rules:
                - when: "{{ outcome.status == 'error' }}"
                  then: { do: fail }
                - else:
                    then: { do: break }
    next:
      spec: { mode: exclusive }
      arcs:
        - step: end
          when: "{{ event.name == 'step.done' }}"

  - step: end
    tool:
      - done: { kind: noop }
```

## Tool support

Tool availability in local mode is runtime-defined. Prefer documenting and validating against the canonical tool docs:
- `documentation/docs/reference/tools/index.md`
- `documentation/docs/reference/tools/http.md`
- `documentation/docs/reference/tools/postgres.md`
- `documentation/docs/reference/tools/python.md`
- `documentation/docs/reference/tools/duckdb.md`
