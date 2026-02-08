---
sidebar_position: 6
title: Workflow Entry, Routing, and Termination (Canonical v10)
description: Canonical rules for initiating execution, Petri-net routing via next.arcs, admission gating, and workflow termination (quiescence)
---

# Workflow Entry, Routing, and Termination (Canonical v10)

This document defines **canonical** semantics for:
- workflow initiation (entry selection),
- step routing (Petri-net **arcs**),
- branch termination,
- playbook completion (quiescence),
- optional finalization/aggregation,

**without requiring reserved step names** such as `step: start` or `step: end`.

The playbook root sections remain:
- `metadata`, `keychain` (optional), `executor` (optional), `workload`, `workflow`, `workbook` (optional)

The `workflow` section remains an **array of steps**.

---

## 1. Model and terminology

### 1.1 Steps as Petri-net transitions
A workflow is modeled as a Petri net / state machine where:
- a **token** represents a unit of control ready to run a step,
- a **step** is a transition that consumes a token when it starts,
- `step.next.arcs[]` defines outgoing **arcs** that produce new tokens for downstream steps.

### 1.2 Server vs worker responsibilities
- The **server (control plane)** is responsible for:
  - selecting the entry step,
  - evaluating step admission (`step.spec.policy.admit.rules`),
  - evaluating routing (`step.next.spec.mode` + `step.next.arcs[].when`),
  - scheduling step-runs to workers,
  - detecting completion (quiescence),
  - persisting the event log and maintaining projections.

- The **worker (data plane)** is responsible for:
  - executing the step pipeline (`step.tool` tasks in order),
  - applying task policy control flow (`retry/jump/break/fail/continue`) via `task.spec.policy.rules`,
  - emitting task and step outcome events.

---

## 2. Entry selection (initial marking)

### 2.1 Default entry rule (MUST)
If no explicit entry is configured, the entry step **MUST** be the first step in the workflow array:

- `entry_step := workflow[0].step`

This ensures deterministic initiation while keeping the workflow as a simple ordered list.

### 2.2 Optional override (MAY)
The runtime MAY support an executor policy to override entry selection:

```yaml
executor:
  spec:
    entry_step: "<step_name>"
```

If `executor.spec.entry_step` is present:
- the server MUST select that step as entry.
- the referenced step name MUST exist in the workflow array.

### 2.3 Initial token
At execution start, the server MUST create exactly one initial token targeting `entry_step` unless an implementation explicitly supports multi-token starts.

---

## 3. Step enablement

### 3.1 Admission policy (server-side)
Canonical v10 has **no** `step.when` field. Enablement is expressed via **step admission policy**:

- `step.spec.policy.admit.rules[]`

Admission rule shape:
```yaml
spec:
  policy:
    admit:
      rules:
        - when: "{{ <bool expr> }}"
          then: { allow: true|false }
        - else:
            then: { allow: true|false }
```

Admission rule:
- a token targeting a step is admitted when the server evaluates `allow: true`.
- if `admit` is omitted, admission defaults to **allow**.

### 3.2 Disabled steps
If admission evaluates to deny:
- the token MUST NOT be scheduled to a worker.
- the runtime MUST define one of:
  - token remains pending until it becomes enabled (default), or
  - token is discarded (optional policy).

Canonical default:
- token remains pending (to support gates/approvals via future `ctx` patches).

---

## 4. Routing via `step.next` arcs

### 4.1 Router semantics
A step may define a `next` router object with outgoing arcs:

```yaml
next:
  spec:
    mode: exclusive|inclusive
  arcs:
    - step: next_step_name
      when: "{{ <bool expr> }}"   # optional (default true)
      args: { ... }               # optional
```

After a step reaches a terminal outcome (`step.done` or `step.failed`, or `loop.done` when a loop is present), the server MUST evaluate `step.next.arcs[]` to determine which new tokens to emit.

### 4.2 Arc guard evaluation
For each arc:
- if `next.arcs[].when` is omitted, it MUST be treated as `true`.
- if present, it is evaluated server-side using available state:
  - `event` (boundary event), `workload`, `ctx`, and incoming `args`
- the evaluation result determines whether the arc **matches**.

### 4.3 Router mode
`next.spec.mode` controls fan-out:

Defaults:
- if omitted, `exclusive` MUST be assumed.

Behavior:
- **exclusive**: first matching arc (YAML order) wins; emit exactly one downstream token.
- **inclusive**: all matching arcs fire; emit one downstream token per match (fan-out).

### 4.4 Arc payloads (`args`)
If an arc includes `args`, they MUST be bound into the downstream token as immutable `args` for that step-run.

`args` should remain small and reference-first. Large payloads MUST be externalized and passed as references.

---

## 5. Default routing and branch termination

### 5.1 No arcs
If a step has no `next` section:
- it represents a leaf transition.
- after it completes, no downstream token is emitted by routing.

### 5.2 No matching arcs
If a step has `next.arcs[]` but none match:
- the runtime MUST treat this as **branch termination** by default:
  - no downstream tokens are emitted.

Optional policy (MAY):
- treat “no match” as an error and fail execution.
If supported, it MUST be explicitly enabled by policy (e.g., `executor.spec.no_next_is_error: true`).

Canonical default:
- “no match” terminates the branch.

---

## 6. Workflow termination (quiescence)

### 6.1 Quiescence definition (MUST)
An execution is complete when **all** are true:

1) **No runnable tokens exist**
- there are no enabled tokens that can be scheduled.

2) **No in-flight step-runs exist**
- there are no leased/running step runs on workers (including retries in progress).

3) **No pending fan-in trackers exist** (if fan-out mode is enabled)
- there are no incomplete join/fan-in groups preventing downstream routing.

This is the Petri-net notion of reaching a marking with no enabled transitions and no active firings.

### 6.2 Completion status
The server MUST compute final status based on terminal step outcomes and policies, e.g.:
- success when all completed branches ended normally,
- failed if any branch ended in a terminal failure and policy requires fail-fast or fail-on-any-error,
- partial if policy allows partial completion.

(Exact final status policy is implementation-defined, but must be explicit.)

---

## 7. Optional finalization / aggregation (without `step: end`)

### 7.1 `final_step` policy (MAY)
To support “run once at the end” behavior without embedding reserved `end` steps, the runtime MAY support:

```yaml
executor:
  spec:
    final_step: "<step_name>"
```

Semantics:
- After quiescence is reached, if `final_step` is configured and not yet executed:
  - the server MUST schedule a single token to run `final_step`.
- After `final_step` reaches terminal outcome, the execution completes.

### 7.2 Final step inputs
The runtime SHOULD provide a finalization summary to `final_step` via `args`, including:
- execution id,
- counts of steps/branches,
- references to result sets (not full payloads),
- failure summaries if any.

### 7.3 Final step failures
If `final_step` fails, final execution status MUST follow policy, e.g.:
- fail the execution (default), or
- mark partial and retain references for inspection.

---

## 8. Relationship to `noop` steps

`kind: noop` is a valid tool kind to support:
- pure routing steps,
- emitting context patches (`set_ctx`, `set_iter`) via task policy rules,
- decision points inside pipelines.

However:
- workflow initiation and termination MUST NOT require `noop` steps or reserved step names.
- entry and termination are defined by the rules above.

---

## 9. Summary (canonical defaults)

- Entry step is **workflow[0]** unless overridden by `executor.spec.entry_step`.
- Steps are enabled by admission (`step.spec.policy.admit`; default allow).
- Routing is defined by `step.next`:
  - default `exclusive`, ordered first-match wins.
- If no arcs match, the branch terminates by default.
- Execution completes by **quiescence** (no runnable tokens, no in-flight runs, no pending fan-in).
- Optional `executor.spec.final_step` allows a single end-of-run aggregation step without requiring `step: end`.
