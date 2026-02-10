---
sidebar_position: 1
title: NoETL DSL
description: Canonical v10 DSL reference for NoETL playbooks (noetl.io/v2)
---

# NoETL DSL Reference (Canonical v10)

The NoETL Domain-Specific Language (DSL) defines how playbooks are structured and executed under the **Canonical v10** model.

## Start Here

- [NoETL Canonical Step Spec (v10)](./step_spec) - Latest decisions (policies, routing, loops, spec layering)
- [DSL Specification (Canonical)](./spec) - Normative playbook/step schema + semantics
- [DSL Specification (Detailed)](./dsl_specification) - Full technical walkthrough
- [Formal Specification (Canonical)](./formal_specification) - Normative execution model and grammar notes

## Runtime

- [Execution Model](./execution_model) - Control plane vs data plane responsibilities
- [Runtime Event Model](./runtime_events) - Canonical event taxonomy and envelope
- [Runtime Results](./runtime_results) - Reference-first storage (ResultRef/Manifest patterns)
- [Pagination](./pagination) - Streaming pagination with `jump`/`break` inside iterations

## Analysis

- [DSL Analysis & Evaluation](./dsl_analysis_and_evaluation) - Turing-completeness, BPMN 2.0 coverage, and Petri net analysis
- [Workflow Patterns Comparison](./workflow_patterns_comparison) - Van der Aalst patterns comparison across NoETL, BPMN, Argo, GitHub Actions, Step Functions

---

## DSL Overview

### Minimal playbook (canonical v10)

```yaml
apiVersion: noetl.io/v2
kind: Playbook

metadata:
  name: example_workflow
  path: workflows/example
  version: "2.0"

keychain:
  - name: pg_k8s
    kind: postgres_credential

workload:
  api_url: "https://api.example.com"

workflow:
  - step: start
    next:
      spec: { mode: exclusive }
      arcs:
        - step: fetch

  - step: fetch
    tool:
      - call:
          kind: http
          method: GET
          url: "{{ workload.api_url }}/ping"
          spec:
            policy:
              rules:
                - when: "{{ outcome.status == 'error' and outcome.http.status in [429,500,502,503,504] }}"
                  then: { do: retry, attempts: 5, backoff: exponential, delay: 2 }
                - when: "{{ outcome.status == 'error' }}"
                  then: { do: fail }
                - else:
                    then:
                      do: break
                      set_ctx:
                        ping_ok: true
    next:
      spec: { mode: exclusive }
      arcs:
        - step: end
          when: "{{ event.name == 'step.done' }}"

  - step: end
    tool:
      - done:
          kind: noop
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Playbook** | Top-level YAML document: `metadata`, optional `keychain`, optional `executor`, `workload`, `workflow`, optional `workbook` |
| **Keychain** | Optional credential declarations resolved before execution; exposed as `keychain.*` (read-only) |
| **Workload** | Immutable merged input (playbook defaults + request payload) |
| **ctx** | Execution-scoped mutable context, patched via task policy actions (`set_ctx`) |
| **iter** | Iteration-scoped mutable context inside loops (`step.loop`), patched via `set_iter` |
| **Step** | Petri-net transition: admission policy + ordered tool pipeline + `next` router arcs |
| **Task** | Labeled tool invocation in a pipeline (evaluated by the worker) |
| **Next router** | `step.next` with `next.spec` + `next.arcs[]` (evaluated by the server) |

### Available Tool Kinds

Tool kinds are implementation-defined and extensible. Common kinds include:
`http`, `postgres`, `duckdb`, `python`, `secrets`, `playbook`, `workbook`, `noop`, `script`.

### Template Namespaces

Access data in templates using these namespaces:

```yaml
# Immutable workload inputs
"{{ workload.api_url }}"

# Resolved credentials (read-only)
"{{ keychain.openai_token }}"

# Execution-scoped context (cross-step)
"{{ ctx.customer_id }}"

# Iteration-scoped context (inside loops)
"{{ iter.endpoint }}"

# Token payload / arc inscription
"{{ args.page_size }}"

# Pipeline locals (inside a step pipeline)
"{{ _prev }}"
"{{ _task }}"

# Outcome envelope (inside task policy evaluation)
"{{ outcome.status }}"

# Boundary event (inside routing evaluation)
"{{ event.name }}"
```

### Step Routing (canonical v10)

Routing is expressed as Petri-net arcs on `step.next`:

```yaml
next:
  spec: { mode: exclusive }
  arcs:
    - step: success_handler
      when: "{{ event.name == 'step.done' }}"
    - step: error_handler
      when: "{{ event.name == 'step.failed' }}"
```

## See Also

- [Playbook Structure](./playbook_structure)
- [Pagination](./pagination)
- [Tools Reference](/docs/reference/tools)
