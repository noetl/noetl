# DSL v2 Refactoring Series: Edge Args + Fan-out Then Implementation

**Document**: 11 of DSL v2 Refactoring Series  
**Status**: Implementation Brief  
**Date**: November 6, 2025  
**Related**: [03_schema_validation_and_linter.md](03_schema_validation_and_linter.md), [07_implementation_tasks_rollout.md](07_implementation_tasks_rollout.md)

---

## Overview

This document specifies the end-to-end implementation of two major routing enhancements for NoETL DSL v2:

1. **Edge Payloads** (`next[].args`): Pass small data structures along routing edges, exposed to target steps as `call.*`
2. **Conditional Fan-out** (`next[].then`): Single condition dispatching multiple targets with individual args

These features enable fine-grained data flow control and parallel execution patterns while maintaining the 4-char key constraint (`step`, `desc`, `when`, `bind`, `loop`, `tool`, `next`) and idempotent execution semantics.

---

## Context

### DSL v2 Step Structure
Current valid top-level keys (4-char constraint):
```yaml
- step: <id>          # Required: unique identifier
  desc: <string>      # Optional: description
  when: <jinja>       # Optional: gating condition
  bind: <object>      # Optional: variable assignments
  loop: <object>      # Optional: iteration config
  tool: <object>      # Optional: action executor
  next: <array>       # Optional: routing edges
```

### Current Routing Behavior
Steps use `next` array with edge objects:
```yaml
next:
  - step: target1
    when: "{{ condition }}"
  - step: target2      # else branch (no when)
```

Rules:
- First edge with truthy `when` is selected (or edge without `when` as fallback)
- Single dispatch: one target per step completion
- At most one "else" edge (no `when` clause)

---

## Feature Specifications

### A. Edge Payloads (`next[].args`)

**Purpose**: Pass sender-computed data to target steps without polluting global context.

**Schema**:
```yaml
next:
  - step: target
    when: "{{ optional_condition }}"
    args:                           # NEW: optional object
      key1: "{{ sender_expression }}"
      key2: value
```

**Evaluation Timing**:
- Rendered in sender's context **after** `tool.result` integration
- Uses full Jinja2 access to `context`, `step.*`, `tool.*`, etc.

**Delivery Mechanism**:
- Merge into target's **call buffer**: `context.step.<target>.call`
- Namespace: accessible as `{{ call.key1 }}`, `{{ call.key2 }}`, etc.
- Scope: read-only during target's `when`, `bind`, and `tool` rendering

**Multiple Arrivals (AND-join)**:
```yaml
# Two predecessors both call stepC
- step: stepA
  next:
    - step: stepC
      args: { a: 1, shared: "fromA" }

- step: stepB
  next:
    - step: stepC
      args: { b: 2, shared: "fromB" }  # overwrites shared

- step: stepC
  when: "{{ call.a and call.b }}"     # waits for both
  bind:
    combined: "{{ call.a + call.b }}"  # can hoist to global
```

**Deep Merge Semantics**:
- Later arrivals overwrite conflicting keys
- Nested objects are merged recursively
- Arrays are replaced (not concatenated)

**Persistence** (recommended):
- Add `step_state.call` JSONB column to persist buffer across restarts
- Serialize/deserialize during context save/load

**Non-Goals**:
- `call.*` is **not** automatically persisted to global context
- Authors must explicitly hoist with `bind` if durable storage needed
- No automatic cleanup of call buffer (cleared on step completion)

---

### B. Conditional Fan-out (`next[].then`)

**Purpose**: Single condition triggering parallel dispatch to multiple targets, each with custom args.

**Schema**:
```yaml
next:
  - when: "{{ fan_condition }}"
    then:                            # NEW: array of targets
      - step: target1
        args: { mode: "urgent" }     # optional per-target args
      - step: target2
        args: { mode: "normal" }
```

**Semantics**:
- Evaluates `when` in sender context (same as edge `when`)
- If truthy, dispatch **all** targets in `then` array
- Each target receives its own `args` (merged into respective call buffers)
- Targets execute independently (no ordering guarantees between them)

**Routing Precedence** (scan `next` array in order):
1. **First edge** (has `step`) with truthy `when` → dispatch that single target
2. **First fan** (has `then`) with truthy `when` → dispatch all `then` targets
3. **Else edge** (edge with no `when`) → fallback single target
4. **No match** → step becomes sink (no successor)

**Example**:
```yaml
- step: decision
  tool: { kind: python, spec: { code: "def main(c,r): return {'score':0.95}" } }
  result: { as: s }
  next:
    - when: "{{ s.score > 0.9 }}"    # Fan: both targets
      then:
        - step: alert_ops
          args: { severity: "critical", channel: "pagerduty" }
        - step: quarantine
          args: { reason: "HIGH_RISK", auto: true }
    - when: "{{ s.score > 0.5 }}"    # Edge: single target
      step: review_queue
      args: { priority: "medium" }
    - step: archive                  # Else edge

- step: alert_ops
  when: "{{ call.severity }}"
  tool: { kind: http, spec: { url: "https://api.pagerduty.com/...", body: "{{ call }}" } }

- step: quarantine
  when: "{{ call.reason }}"
  tool: { kind: postgres, spec: { query: "INSERT INTO quarantine ..." } }
```

**Backward Compatibility**:
- Existing workflows with edge-only `next` arrays unchanged
- Schema uses `oneOf` discriminator: edge (has `step`) vs fan (has `then`)

---

## Implementation Plan

### 1. Schema Changes (`scripts/workflow-steps.v2.json`)

**Add `nextEdge` definition**:
```json
{
  "$defs": {
    "nextEdge": {
      "type": "object",
      "properties": {
        "step": { "$ref": "#/$defs/stepId" },
        "when": { "$ref": "#/$defs/jinjaExpr" },
        "args": { 
          "type": "object",
          "additionalProperties": true
        }
      },
      "required": ["step"],
      "additionalProperties": false,
      "description": "Single-target routing edge with optional condition and payload"
    }
  }
}
```

**Add `nextFan` definition**:
```json
{
  "$defs": {
    "nextFan": {
      "type": "object",
      "properties": {
        "when": { "$ref": "#/$defs/jinjaExpr" },
        "then": {
          "type": "array",
          "minItems": 1,
          "items": {
            "type": "object",
            "properties": {
              "step": { "$ref": "#/$defs/stepId" },
              "args": { 
                "type": "object",
                "additionalProperties": true
              }
            },
            "required": ["step"],
            "additionalProperties": false
          },
          "description": "Array of target steps, each with optional args"
        }
      },
      "required": ["when", "then"],
      "additionalProperties": false,
      "description": "Conditional fan-out to multiple targets"
    }
  }
}
```

**Update `next` property**:
```json
{
  "properties": {
    "next": {
      "type": "array",
      "items": {
        "oneOf": [
          { "$ref": "#/$defs/nextEdge" },
          { "$ref": "#/$defs/nextFan" }
        ]
      },
      "minItems": 1,
      "description": "Routing edges (single-target) or fan-out (multi-target)"
    }
  }
}
```

---

### 2. Linter Updates (`scripts/lint_dsl_v2.py`)

**Discriminator Helpers**:
```python
def is_edge(item: dict) -> bool:
    """Edge has 'step' key."""
    return isinstance(item, dict) and "step" in item

def is_fan(item: dict) -> bool:
    """Fan has 'when' and 'then' keys."""
    return isinstance(item, dict) and "when" in item and "then" in item
```

**Validation Rules**:

1. **Next item shape**:
   ```python
   for i, item in enumerate(step.get("next", [])):
       if not is_edge(item) and not is_fan(item):
           errors.append(f"step={sid} next[{i}]: must be edge (has 'step') or fan (has 'when'+'then')")
   ```

2. **Edge args type**:
   ```python
   if is_edge(item):
       args = item.get("args")
       if args is not None and not isinstance(args, dict):
           errors.append(f"step={sid} next[{i}].args: must be object, got {type(args).__name__}")
       if args and "step" in args:
           warnings.append(f"step={sid} next[{i}].args: contains reserved key 'step'")
   ```

3. **Fan args type**:
   ```python
   if is_fan(item):
       for j, target in enumerate(item["then"]):
           if "step" not in target:
               errors.append(f"step={sid} next[{i}].then[{j}]: missing required 'step' key")
           args = target.get("args")
           if args is not None and not isinstance(args, dict):
               errors.append(f"step={sid} next[{i}].then[{j}].args: must be object")
           if args and "step" in args:
               warnings.append(f"step={sid} next[{i}].then[{j}].args: contains reserved key 'step'")
   ```

4. **Single else edge**:
   ```python
   else_edges = [item for item in step.get("next", []) if is_edge(item) and "when" not in item]
   if len(else_edges) > 1:
       errors.append(f"step={sid}: multiple else edges (edges without 'when')")
   ```

5. **Args size warning**:
   ```python
   import json
   MAX_ARGS_SIZE = 8192  # 8KB
   
   if args:
       size = len(json.dumps(args, ensure_ascii=False))
       if size > MAX_ARGS_SIZE:
           warnings.append(f"step={sid} next[{i}].args: {size} bytes exceeds recommended {MAX_ARGS_SIZE}")
   ```

**No Changes Needed**:
- Sink detection (already handles missing `next`)
- Top-level key validation (4-char constraint unchanged)
- Step ID reference validation (add edge/fan targets to graph)

---

### 3. Router Implementation (`noetl/server/router.py`)

**Context Helper** (or in `noetl/server/context.py`):
```python
def merge_call_payload(context: dict, target_step_id: str, payload: dict) -> None:
    """
    Deep merge payload into target step's call buffer.
    Later arrivals overwrite conflicting keys.
    
    Args:
        context: global execution context
        target_step_id: target step identifier
        payload: args dict from next[].args
    """
    step_node = context.setdefault("step", {}).setdefault(target_step_id, {})
    call_buffer = step_node.setdefault("call", {})
    
    def deep_merge(target: dict, source: dict) -> None:
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                deep_merge(target[key], value)
            else:
                target[key] = value
    
    deep_merge(call_buffer, payload or {})


def get_call_buffer(context: dict, step_id: str) -> dict:
    """Retrieve call buffer for a step (for evaluation scope)."""
    return context.get("step", {}).get(step_id, {}).get("call", {})


def clear_call_buffer(context: dict, step_id: str) -> None:
    """Clear call buffer after step completes (optional cleanup)."""
    step_node = context.get("step", {}).get(step_id, {})
    if step_node and "call" in step_node:
        del step_node["call"]
```

**Routing Logic** (pseudo-code for clarity):
```python
def route_next_steps(context: dict, step_def: dict, step_id: str) -> list[str]:
    """
    Evaluate next[] array and dispatch successor(s).
    
    Returns:
        List of dispatched step IDs
    """
    next_array = step_def.get("next", [])
    if not next_array:
        return []  # sink step
    
    dispatched = []
    
    # Phase 1: Try edges (has 'step')
    for item in next_array:
        if "step" in item:
            condition = item.get("when")
            if condition is None or eval_when(context, condition):
                # Render args in sender context
                args = render_args(context, item.get("args", {}))
                target_id = item["step"]
                
                # Merge into target's call buffer
                merge_call_payload(context, target_id, args)
                
                # Dispatch (park until target.when satisfied)
                call_step(context, target_id)
                dispatched.append(target_id)
                return dispatched  # first match wins
    
    # Phase 2: Try fans (has 'then')
    for item in next_array:
        if "then" in item:
            condition = item.get("when")
            if eval_when(context, condition):
                # Dispatch all targets in then[]
                for target_spec in item["then"]:
                    args = render_args(context, target_spec.get("args", {}))
                    target_id = target_spec["step"]
                    
                    merge_call_payload(context, target_id, args)
                    call_step(context, target_id)
                    dispatched.append(target_id)
                return dispatched  # first fan match wins
    
    # Phase 3: Else edge (no when)
    for item in next_array:
        if "step" in item and "when" not in item:
            args = render_args(context, item.get("args", {}))
            target_id = item["step"]
            
            merge_call_payload(context, target_id, args)
            call_step(context, target_id)
            dispatched.append(target_id)
            return dispatched
    
    return []  # no match = sink


def render_args(context: dict, args_template: dict) -> dict:
    """
    Render Jinja2 expressions in args dict using sender context.
    Recursively process nested structures.
    """
    if not isinstance(args_template, dict):
        return {}
    
    result = {}
    for key, value in args_template.items():
        if isinstance(value, str):
            result[key] = render_jinja(context, value)
        elif isinstance(value, dict):
            result[key] = render_args(context, value)
        elif isinstance(value, list):
            result[key] = [
                render_args(context, v) if isinstance(v, dict) else 
                render_jinja(context, v) if isinstance(v, str) else v
                for v in value
            ]
        else:
            result[key] = value
    return result


def call_step(context: dict, target_id: str) -> None:
    """
    Enqueue or park step for execution.
    - If target.when not satisfied: mark as parked (waiting for call buffer)
    - If target.when satisfied: dispatch immediately
    - If already done (status.done=true): skip (idempotence)
    """
    step_def = get_step_definition(context, target_id)
    step_status = get_step_status(context, target_id)
    
    if step_status.get("done"):
        return  # already executed, ignore repeat calls
    
    # Evaluate when with call buffer in scope
    call_buffer = get_call_buffer(context, target_id)
    eval_scope = {**context, "call": call_buffer}
    
    when_expr = step_def.get("when")
    if when_expr and not eval_when(eval_scope, when_expr):
        mark_parked(context, target_id)  # waiting for more call data
        return
    
    # Ready to execute
    enqueue_for_execution(context, target_id)
```

**Evaluation Scope Helper**:
```python
def eval_when(context: dict, expression: str, target_step_id: str = None) -> bool:
    """
    Evaluate Jinja2 when expression.
    If target_step_id provided, inject call buffer into scope.
    """
    scope = dict(context)
    if target_step_id:
        scope["call"] = get_call_buffer(context, target_step_id)
    
    template = jinja_env.from_string("{{ " + expression + " }}")
    result = template.render(**scope)
    return bool(result and result.lower() not in ("false", "0", ""))
```

---

### 4. Persistence (`noetl/server/database.py` or migration)

**Schema Migration**:
```sql
-- Add call buffer column to step_state table
ALTER TABLE step_state 
ADD COLUMN call JSONB DEFAULT '{}';

-- Index for queries filtering on call buffer keys
CREATE INDEX idx_step_state_call ON step_state USING gin(call);
```

**Serialization**:
```python
def save_step_state(execution_id: str, step_id: str, context: dict) -> None:
    """Save step state including call buffer."""
    step_node = context.get("step", {}).get(step_id, {})
    call_buffer = step_node.get("call", {})
    
    db.execute(
        """
        INSERT INTO step_state (execution_id, step_id, status, context, call)
        VALUES (%(exec_id)s, %(step_id)s, %(status)s, %(context)s, %(call)s)
        ON CONFLICT (execution_id, step_id) DO UPDATE
        SET status = EXCLUDED.status,
            context = EXCLUDED.context,
            call = EXCLUDED.call,
            updated_at = NOW()
        """,
        {
            "exec_id": execution_id,
            "step_id": step_id,
            "status": step_node.get("status", "pending"),
            "context": json.dumps(context),
            "call": json.dumps(call_buffer),
        }
    )


def load_step_state(execution_id: str, step_id: str) -> dict:
    """Load step state including call buffer."""
    row = db.fetch_one(
        "SELECT status, context, call FROM step_state WHERE execution_id = %s AND step_id = %s",
        (execution_id, step_id)
    )
    
    context = json.loads(row["context"])
    call_buffer = json.loads(row["call"]) if row["call"] else {}
    
    # Inject call buffer into context
    context.setdefault("step", {}).setdefault(step_id, {})["call"] = call_buffer
    
    return context
```

---

### 5. Test Fixtures

#### Valid Fixtures (`tests/fixtures/workflows/v2/valid/`)

**`next_edge_args.yaml`**:
```yaml
workflow:
  - step: start
    tool: 
      kind: python
      spec: 
        code: |
          def main(context, runtime):
              return {"user_id": 42, "score": 0.85}
    result: { as: start_result }
    next:
      - step: process
        args:
          uid: "{{ start_result.user_id }}"
          level: "{{ 'high' if start_result.score > 0.8 else 'low' }}"
          timestamp: "{{ now() }}"

  - step: process
    when: "{{ call.uid and call.level }}"
    bind:
      user_id: "{{ call.uid }}"
      level: "{{ call.level }}"
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {
                  "processed": True,
                  "user": context["user_id"],
                  "level": context["level"]
              }
    result: { as: process_result }
```

**`next_then_fan.yaml`**:
```yaml
workflow:
  - step: start
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {"score": 0.95, "reason": "anomaly_detected"}
    result: { as: decision }
    next:
      - when: "{{ decision.score > 0.9 }}"
        then:
          - step: alert_ops
            args:
              severity: "critical"
              channel: "pagerduty"
              message: "{{ decision.reason }}"
          - step: quarantine
            args:
              reason: "{{ decision.reason }}"
              auto: true
      - when: "{{ decision.score > 0.5 }}"
        step: review
        args:
          priority: "medium"
      - step: archive

  - step: alert_ops
    when: "{{ call.severity and call.channel }}"
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {
                  "alerted": True,
                  "severity": runtime.get("call", {}).get("severity")
              }

  - step: quarantine
    when: "{{ call.reason }}"
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {
                  "quarantined": True,
                  "reason": runtime.get("call", {}).get("reason")
              }

  - step: review
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {"reviewed": True}

  - step: archive
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {"archived": True}
```

**`next_and_join.yaml`** (multiple predecessors):
```yaml
workflow:
  - step: start
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {"ok": True}
    next:
      - step: branch_a
      - step: branch_b

  - step: branch_a
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {"a_value": 10}
    result: { as: a_res }
    next:
      - step: join
        args:
          a: "{{ a_res.a_value }}"
          source: "branch_a"

  - step: branch_b
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {"b_value": 20}
    result: { as: b_res }
    next:
      - step: join
        args:
          b: "{{ b_res.b_value }}"
          source: "branch_b"

  - step: join
    when: "{{ call.a and call.b }}"  # waits for both
    bind:
      total: "{{ call.a + call.b }}"
    tool:
      kind: python
      spec:
        code: |
          def main(context, runtime):
              return {
                  "sum": context["total"],
                  "sources": [
                      runtime.get("call", {}).get("source", "unknown")
                  ]
              }
```

#### Invalid Fixtures (`tests/fixtures/workflows/v2/invalid/`)

**`next_args_not_object.yaml`**:
```yaml
workflow:
  - step: bad
    next:
      - step: target
        args: "this should be an object"  # ERROR: args must be object
```

**`next_then_missing_step.yaml`**:
```yaml
workflow:
  - step: bad
    next:
      - when: "{{ true }}"
        then:
          - args: { x: 1 }  # ERROR: missing required 'step' key
```

**`next_then_no_when.yaml`**:
```yaml
workflow:
  - step: bad
    next:
      - then:  # ERROR: fan requires 'when'
          - step: target1
          - step: target2
```

**`next_multiple_else.yaml`**:
```yaml
workflow:
  - step: bad
    next:
      - step: target1  # else edge 1
      - step: target2  # else edge 2 (ERROR: only one allowed)
```

---

### 6. Test Suite

#### `tests/test_dsl_v2_validation.py` (extend existing)

**Schema Tests**:
```python
def test_next_edge_args_valid():
    """Edge args must be object if present."""
    workflow = {
        "workflow": [
            {
                "step": "a",
                "next": [
                    {"step": "b", "args": {"x": 1, "y": "{{ expr }}"}}
                ]
            },
            {"step": "b"}
        ]
    }
    errors = validate_schema(workflow)
    assert not errors


def test_next_fan_valid():
    """Fan must have when and then array."""
    workflow = {
        "workflow": [
            {
                "step": "a",
                "next": [
                    {
                        "when": "{{ true }}",
                        "then": [
                            {"step": "b", "args": {"x": 1}},
                            {"step": "c"}
                        ]
                    }
                ]
            },
            {"step": "b"},
            {"step": "c"}
        ]
    }
    errors = validate_schema(workflow)
    assert not errors


def test_next_args_not_object_invalid():
    """Args must be object, not string."""
    workflow = {
        "workflow": [
            {
                "step": "a",
                "next": [{"step": "b", "args": "invalid"}]
            }
        ]
    }
    errors = validate_schema(workflow)
    assert any("args" in e.lower() for e in errors)


def test_next_then_missing_step_invalid():
    """Fan targets must have step key."""
    workflow = {
        "workflow": [
            {
                "step": "a",
                "next": [
                    {"when": "{{ true }}", "then": [{"args": {"x": 1}}]}
                ]
            }
        ]
    }
    errors = validate_schema(workflow)
    assert any("step" in e.lower() for e in errors)
```

#### `tests/test_routing_edge_args_then.py` (new file)

```python
import pytest
from noetl.server.router import (
    route_next_steps,
    merge_call_payload,
    get_call_buffer,
    render_args,
)


class TestEdgeArgs:
    """Test next[].args payload delivery."""
    
    def test_args_rendered_in_sender_context(self):
        """Args use sender's context for Jinja rendering."""
        context = {"user": "alice", "score": 0.9}
        step_def = {
            "step": "sender",
            "next": [
                {
                    "step": "receiver",
                    "args": {
                        "name": "{{ user }}",
                        "level": "{{ 'high' if score > 0.8 else 'low' }}"
                    }
                }
            ]
        }
        
        route_next_steps(context, step_def, "sender")
        
        call = get_call_buffer(context, "receiver")
        assert call["name"] == "alice"
        assert call["level"] == "high"
    
    
    def test_args_merged_into_call_buffer(self):
        """Multiple arrivals merge into call buffer."""
        context = {}
        
        merge_call_payload(context, "target", {"a": 1, "shared": "first"})
        merge_call_payload(context, "target", {"b": 2, "shared": "second"})
        
        call = get_call_buffer(context, "target")
        assert call == {"a": 1, "b": 2, "shared": "second"}  # later wins
    
    
    def test_nested_merge(self):
        """Nested objects deep merge correctly."""
        context = {}
        
        merge_call_payload(context, "target", {"config": {"x": 1, "y": 2}})
        merge_call_payload(context, "target", {"config": {"y": 3, "z": 4}})
        
        call = get_call_buffer(context, "target")
        assert call["config"] == {"x": 1, "y": 3, "z": 4}
    
    
    def test_call_accessible_in_target_when(self):
        """Target's when can access call.* namespace."""
        context = {}
        merge_call_payload(context, "target", {"ready": True, "count": 5})
        
        step_def = {
            "step": "target",
            "when": "{{ call.ready and call.count > 3 }}"
        }
        
        from noetl.server.router import eval_when
        result = eval_when(context, step_def["when"], "target")
        assert result is True


class TestConditionalFanout:
    """Test next[].then multi-target dispatch."""
    
    def test_fan_dispatches_all_targets(self):
        """When fan condition true, all then[] targets dispatched."""
        context = {"trigger": True}
        step_def = {
            "step": "decision",
            "next": [
                {
                    "when": "{{ trigger }}",
                    "then": [
                        {"step": "target1", "args": {"priority": "high"}},
                        {"step": "target2", "args": {"priority": "low"}}
                    ]
                }
            ]
        }
        
        dispatched = route_next_steps(context, step_def, "decision")
        
        assert "target1" in dispatched
        assert "target2" in dispatched
        assert get_call_buffer(context, "target1")["priority"] == "high"
        assert get_call_buffer(context, "target2")["priority"] == "low"
    
    
    def test_fan_condition_false_skips(self):
        """When fan condition false, targets not dispatched."""
        context = {"trigger": False}
        step_def = {
            "step": "decision",
            "next": [
                {
                    "when": "{{ trigger }}",
                    "then": [
                        {"step": "target1"},
                        {"step": "target2"}
                    ]
                },
                {"step": "fallback"}
            ]
        }
        
        dispatched = route_next_steps(context, step_def, "decision")
        
        assert "target1" not in dispatched
        assert "target2" not in dispatched
        assert "fallback" in dispatched


class TestRoutingPrecedence:
    """Test edge vs fan evaluation order."""
    
    def test_edge_before_fan(self):
        """First truthy edge dispatched before any fan."""
        context = {"score": 0.7}
        step_def = {
            "step": "choice",
            "next": [
                {"step": "edge1", "when": "{{ score > 0.5 }}"},  # matches first
                {
                    "when": "{{ score > 0.6 }}",  # also matches but not reached
                    "then": [{"step": "fan1"}, {"step": "fan2"}]
                }
            ]
        }
        
        dispatched = route_next_steps(context, step_def, "choice")
        
        assert dispatched == ["edge1"]
        assert "fan1" not in dispatched
    
    
    def test_fan_when_no_edge_matches(self):
        """Fan evaluated after all edges fail."""
        context = {"score": 0.7}
        step_def = {
            "step": "choice",
            "next": [
                {"step": "edge1", "when": "{{ score > 0.9 }}"},  # false
                {
                    "when": "{{ score > 0.6 }}",  # true
                    "then": [{"step": "fan1"}, {"step": "fan2"}]
                }
            ]
        }
        
        dispatched = route_next_steps(context, step_def, "choice")
        
        assert "fan1" in dispatched
        assert "fan2" in dispatched
        assert "edge1" not in dispatched
    
    
    def test_else_edge_fallback(self):
        """Else edge used when no edge/fan matches."""
        context = {"score": 0.3}
        step_def = {
            "step": "choice",
            "next": [
                {"step": "edge1", "when": "{{ score > 0.9 }}"},
                {"when": "{{ score > 0.6 }}", "then": [{"step": "fan1"}]},
                {"step": "fallback"}  # else edge
            ]
        }
        
        dispatched = route_next_steps(context, step_def, "choice")
        
        assert dispatched == ["fallback"]


class TestAndJoin:
    """Test multiple predecessors with call buffer."""
    
    def test_target_waits_for_all_predecessors(self):
        """Target with call.a and call.b gating waits for both."""
        context = {}
        
        # First predecessor arrives
        merge_call_payload(context, "join", {"a": 10})
        step_def = {"step": "join", "when": "{{ call.a and call.b }}"}
        
        from noetl.server.router import eval_when
        assert not eval_when(context, step_def["when"], "join")  # not ready
        
        # Second predecessor arrives
        merge_call_payload(context, "join", {"b": 20})
        assert eval_when(context, step_def["when"], "join")  # now ready
    
    
    def test_call_buffer_cleared_after_execution(self):
        """Call buffer optionally cleared after step completes."""
        from noetl.server.router import clear_call_buffer
        
        context = {}
        merge_call_payload(context, "step1", {"x": 1})
        
        clear_call_buffer(context, "step1")
        
        call = get_call_buffer(context, "step1")
        assert call == {}


class TestIdempotence:
    """Test repeat dispatch handling."""
    
    def test_completed_step_ignores_repeat_calls(self):
        """Step with done=true ignores additional dispatch."""
        context = {
            "step": {
                "target": {
                    "status": {"done": True},
                    "call": {"x": 1}
                }
            }
        }
        
        from noetl.server.router import call_step
        
        # Should not re-execute
        call_step(context, "target")
        
        # Call buffer unchanged (no new merge)
        assert get_call_buffer(context, "target") == {"x": 1}
```

---

### 7. Documentation Updates

#### `README.md` (add section)

**Location**: After "Routing with next" section

```markdown
### Edge Payloads (`next[].args`)

Pass small data structures along routing edges without polluting global context:

```yaml
- step: sender
  tool: 
    kind: python
    spec: { code: "def main(c,r): return {'user_id':42, 'score':0.9}" }
  result: { as: res }
  next:
    - step: receiver
      args:
        uid: "{{ res.user_id }}"
        level: "{{ 'high' if res.score > 0.8 else 'low' }}"

- step: receiver
  when: "{{ call.uid }}"              # access via call.*
  bind:
    user_id: "{{ call.uid }}"         # hoist to global if needed
  tool:
    kind: http
    spec:
      url: "https://api.example.com/users/{{ call.uid }}"
      body: { level: "{{ call.level }}" }
```

**Key Points**:
- `args` rendered in **sender's context** (after `result` integration)
- Accessible in target's `when`, `bind`, and `tool` as `{{ call.* }}`
- Multiple arrivals **merge** (later overwrites conflicting keys)
- Not persisted to global context unless hoisted with `bind`

---

### Conditional Fan-out (`next[].then`)

Dispatch multiple targets with a single condition:

```yaml
- step: decision
  tool:
    kind: python
    spec: { code: "def main(c,r): return {'score':0.95}" }
  result: { as: s }
  next:
    - when: "{{ s.score > 0.9 }}"     # fan: both targets
      then:
        - step: alert_ops
          args: { severity: "critical", channel: "pagerduty" }
        - step: quarantine
          args: { reason: "HIGH_RISK" }
    
    - when: "{{ s.score > 0.5 }}"     # edge: single target
      step: review_queue
      args: { priority: "medium" }
    
    - step: archive                   # else edge

- step: alert_ops
  when: "{{ call.severity }}"
  tool: { kind: http, spec: { url: "..." } }

- step: quarantine
  when: "{{ call.reason }}"
  tool: { kind: postgres, spec: { query: "INSERT INTO quarantine ..." } }
```

**Evaluation Order**:
1. First **edge** (has `step`) with truthy `when` → dispatch single target
2. First **fan** (has `then`) with truthy `when` → dispatch all `then[]` targets
3. **Else edge** (edge without `when`) → fallback
4. **No match** → step becomes sink

**Use Cases**:
- Parallel notifications (Slack + PagerDuty)
- Multi-stage error handling (log + quarantine + alert)
- Conditional branches with shared context
```

---

## Acceptance Criteria

### Schema & Validation
- ✅ JSON Schema accepts `next[].args` (object, optional)
- ✅ JSON Schema accepts `next[].then` (array with `when` required)
- ✅ Schema uses `oneOf` discriminator for edge vs fan
- ✅ Linter validates edge/fan shapes
- ✅ Linter enforces single else edge rule
- ✅ Linter checks `args` type (must be object)
- ✅ Linter warns on reserved keys in `args` ("step")
- ✅ Linter warns on oversized `args` (> 8KB)

### Router Implementation
- ✅ Edge `args` rendered in sender context (post-result)
- ✅ Fan targets dispatched in order with individual `args`
- ✅ Call buffer merges arrivals (deep merge, later wins)
- ✅ Target `when` can access `call.*` namespace
- ✅ Routing precedence: edge → fan → else → sink
- ✅ Idempotence: completed steps (done=true) ignore repeat calls
- ✅ Parked steps wait until `when` satisfied

### Persistence
- ✅ Optional: `step_state.call` JSONB column persists buffer
- ✅ Serialization/deserialization includes call buffer
- ✅ Call buffer survives worker restarts

### Testing
- ✅ Schema validation tests (valid + invalid fixtures)
- ✅ Linter tests (edge/fan shapes, else edge, args type)
- ✅ Router tests:
  - Args rendering and delivery
  - Deep merge semantics
  - Fan-out dispatch
  - Routing precedence
  - AND-join (multiple predecessors)
  - Idempotence
- ✅ End-to-end integration tests with example workflows

### Documentation
- ✅ README updated with edge args examples
- ✅ README updated with fan-out examples
- ✅ Inline code comments explain merge/dispatch logic
- ✅ This implementation doc complete

---

## Execution Plan

### Phase 1: Schema & Validation (1-2 hours)
```bash
# Edit schema
vim scripts/workflow-steps.v2.json

# Update linter
vim scripts/lint_dsl_v2.py

# Validate schema loads
python scripts/validate_dsl_v2.py

# Run linter tests
pytest -xvs tests/test_dsl_v2_validation.py::test_next_edge_args_valid
pytest -xvs tests/test_dsl_v2_validation.py::test_next_fan_valid
```

### Phase 2: Router Implementation (2-3 hours)
```bash
# Implement context helpers
vim noetl/server/context.py

# Implement routing logic
vim noetl/server/router.py

# Unit tests
pytest -xvs tests/test_routing_edge_args_then.py::TestEdgeArgs
pytest -xvs tests/test_routing_edge_args_then.py::TestConditionalFanout
```

### Phase 3: Persistence (1 hour, optional)
```bash
# Create migration
vim noetl/migrations/add_call_buffer.sql

# Update serialization
vim noetl/server/database.py

# Test persistence
pytest -xvs tests/test_step_state_persistence.py
```

### Phase 4: Fixtures & Integration (1-2 hours)
```bash
# Create valid fixtures
vim tests/fixtures/workflows/v2/valid/next_edge_args.yaml
vim tests/fixtures/workflows/v2/valid/next_then_fan.yaml
vim tests/fixtures/workflows/v2/valid/next_and_join.yaml

# Create invalid fixtures
vim tests/fixtures/workflows/v2/invalid/next_args_not_object.yaml
vim tests/fixtures/workflows/v2/invalid/next_then_missing_step.yaml

# Run fixture validation
pytest -xvs tests/test_dsl_v2_validation.py::test_valid_fixtures_ok

# End-to-end tests
pytest -xvs tests/test_routing_edge_args_then.py
```

### Phase 5: Documentation & Review (30 min)
```bash
# Update README
vim README.md

# Validate all tests pass
pytest -q

# Lint examples
make dsl.validate dsl.lint

# Code review checklist:
# - 4-char keys unchanged
# - Idempotence preserved
# - Call buffer not auto-persisted to global
# - Deep merge correct
# - Routing precedence documented
```

---

## Implementation Notes

### Design Decisions

**Why call.* namespace?**
- Distinguishes edge data from global context
- Prevents accidental name collisions
- Clear semantic: "this data was passed to me"
- Read-only scope encourages explicit hoisting

**Why deep merge?**
- Enables incremental data assembly from multiple sources
- Nested config objects remain intact
- Predictable conflict resolution (later wins)

**Why evaluate args in sender context?**
- Sender has full visibility into its own execution state
- Avoids "what did the sender know?" ambiguity
- Consistent with step-local rendering everywhere else

**Why routing precedence edge → fan → else?**
- Backward compatible (existing edge-only workflows unchanged)
- Single-target (edge) more specific than multi-target (fan)
- Else remains true fallback (lowest priority)

**Why not auto-persist call.* to global?**
- Prevents hidden state accumulation
- Forces intentional data lifetime decisions
- Call buffer is transient handoff mechanism
- Authors use `bind` for durable storage

### Edge Cases

**Empty args**:
```yaml
next:
  - step: target
    args: {}  # valid, no-op (target sees empty call)
```

**No when on edge with args**:
```yaml
next:
  - step: target
    args: { x: 1 }  # valid, unconditional dispatch with args
```

**Fan with single target**:
```yaml
next:
  - when: "{{ cond }}"
    then:
      - step: single  # valid but unusual (use edge instead)
```

**Nested fan**:
```yaml
next:
  - when: "{{ outer }}"
    then:
      - step: inner
        # inner.next can have its own fan
```

**Circular call references**:
```yaml
next:
  - step: B
    args: { x: "{{ call.y }}" }  # call.y doesn't exist in A's context
    # Renders to empty/undefined, not circular
```

### Performance Considerations

**Args size limits**:
- Recommended: < 8KB per args object
- Enforced: linter warning at 8KB, hard limit at 64KB (database constraint)
- For large data: use storage references (S3 key, DB row ID)

**Fan-out scale**:
- Recommended: < 10 targets per fan
- Enforced: none (database transaction handles hundreds)
- For massive fan-out: use `loop` with async mode

**Call buffer cleanup**:
- Optional: clear after step execution
- Trade-off: memory vs debuggability
- Default: preserve for post-mortem analysis

### Migration Path

**Existing workflows**: No changes required
- Edge-only `next` arrays work identically
- `args` and `then` are purely additive

**Gradual adoption**:
1. Start with simple edge args (low risk)
2. Replace parallel step launches with fan-out
3. Refactor join patterns to use call buffer

**Rollback safety**:
- New schema backward-compatible with v2.0 workflows
- Call buffer column nullable (defaults to `{}`)
- Router degrades gracefully if args/then absent

---

## Related Work

**Previous Documents**:
- [03_schema_validation_and_linter.md](03_schema_validation_and_linter.md): Base schema structure
- [07_implementation_tasks_rollout.md](07_implementation_tasks_rollout.md): Rollout strategy
- [08_observability_retries_timeouts_compensation.md](08_observability_retries_timeouts_compensation.md): Error handling context

**Future Work**:
- Edge timeouts: `next[].timeout` for long-running joins
- Call buffer TTL: auto-expire stale data
- Explicit join step type: declarative AND/OR gating
- Call buffer inspection API: debug stuck joins

---

## Success Metrics

**Quantitative**:
- Zero schema validation failures on existing workflows
- < 5% performance overhead for edge args rendering
- < 100ms added latency for fan dispatch (vs sequential)

**Qualitative**:
- Reduced boilerplate for parallel notifications
- Simplified join patterns (no manual context coordination)
- Improved readability (data flow visible in routing)

**Adoption Indicators**:
- 20% of new workflows use edge args within 3 months
- 10% of workflows refactored to use fan-out
- Zero production incidents related to call buffer bugs

---

## Appendix A: Complete Schema Diff

```diff
--- a/scripts/workflow-steps.v2.json
+++ b/scripts/workflow-steps.v2.json
@@ -45,12 +45,50 @@
     },
     "next": {
       "type": "array",
-      "items": { "$ref": "#/$defs/nextEdge" },
+      "items": {
+        "oneOf": [
+          { "$ref": "#/$defs/nextEdge" },
+          { "$ref": "#/$defs/nextFan" }
+        ]
+      },
       "minItems": 1
     },
     "nextEdge": {
       "type": "object",
       "properties": {
         "step": { "$ref": "#/$defs/stepId" },
-        "when": { "$ref": "#/$defs/jinjaExpr" }
+        "when": { "$ref": "#/$defs/jinjaExpr" },
+        "args": {
+          "type": "object",
+          "additionalProperties": true,
+          "description": "Payload passed to target step's call buffer"
+        }
       },
       "required": ["step"],
       "additionalProperties": false
+    },
+    "nextFan": {
+      "type": "object",
+      "properties": {
+        "when": {
+          "$ref": "#/$defs/jinjaExpr",
+          "description": "Condition to dispatch all then[] targets"
+        },
+        "then": {
+          "type": "array",
+          "minItems": 1,
+          "items": {
+            "type": "object",
+            "properties": {
+              "step": { "$ref": "#/$defs/stepId" },
+              "args": {
+                "type": "object",
+                "additionalProperties": true
+              }
+            },
+            "required": ["step"],
+            "additionalProperties": false
+          }
+        }
+      },
+      "required": ["when", "then"],
+      "additionalProperties": false
     }
```

---

## Appendix B: Router Pseudo-code (Full)

```python
# noetl/server/router.py

from typing import Any, Optional
import json
from jinja2 import Template, Environment


def route_next_steps(
    context: dict[str, Any],
    step_def: dict[str, Any],
    step_id: str
) -> list[str]:
    """
    Evaluate next[] array and dispatch successors.
    
    Returns list of dispatched step IDs.
    """
    next_array = step_def.get("next", [])
    if not next_array:
        return []
    
    # Phase 1: Edges (has 'step')
    for item in next_array:
        if "step" in item:
            cond = item.get("when")
            if cond is None or eval_when(context, cond):
                args = render_args(context, item.get("args", {}))
                target = item["step"]
                merge_call_payload(context, target, args)
                call_step(context, target)
                return [target]
    
    # Phase 2: Fans (has 'then')
    for item in next_array:
        if "then" in item:
            cond = item.get("when")
            if eval_when(context, cond):
                dispatched = []
                for spec in item["then"]:
                    args = render_args(context, spec.get("args", {}))
                    target = spec["step"]
                    merge_call_payload(context, target, args)
                    call_step(context, target)
                    dispatched.append(target)
                return dispatched
    
    # Phase 3: Else edge
    for item in next_array:
        if "step" in item and "when" not in item:
            args = render_args(context, item.get("args", {}))
            target = item["step"]
            merge_call_payload(context, target, args)
            call_step(context, target)
            return [target]
    
    return []  # sink


def merge_call_payload(
    context: dict[str, Any],
    target_step_id: str,
    payload: dict[str, Any]
) -> None:
    """Deep merge payload into target's call buffer."""
    step_node = context.setdefault("step", {}).setdefault(target_step_id, {})
    call = step_node.setdefault("call", {})
    
    def deep_merge(target: dict, source: dict) -> None:
        for k, v in source.items():
            if (k in target and 
                isinstance(target[k], dict) and 
                isinstance(v, dict)):
                deep_merge(target[k], v)
            else:
                target[k] = v
    
    deep_merge(call, payload)


def get_call_buffer(context: dict[str, Any], step_id: str) -> dict[str, Any]:
    """Retrieve call buffer for step."""
    return context.get("step", {}).get(step_id, {}).get("call", {})


def clear_call_buffer(context: dict[str, Any], step_id: str) -> None:
    """Clear call buffer after step execution."""
    step_node = context.get("step", {}).get(step_id, {})
    if "call" in step_node:
        del step_node["call"]


def render_args(context: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Recursively render Jinja2 in args dict."""
    if not isinstance(args, dict):
        return {}
    
    result = {}
    for key, value in args.items():
        if isinstance(value, str):
            result[key] = render_jinja(context, value)
        elif isinstance(value, dict):
            result[key] = render_args(context, value)
        elif isinstance(value, list):
            result[key] = [
                render_args(context, v) if isinstance(v, dict) else
                render_jinja(context, v) if isinstance(v, str) else v
                for v in value
            ]
        else:
            result[key] = value
    return result


def render_jinja(context: dict[str, Any], template_str: str) -> Any:
    """Render single Jinja2 template string."""
    if not template_str or "{{" not in template_str:
        return template_str
    
    env = Environment(autoescape=False)
    template = env.from_string(template_str)
    return template.render(**context)


def eval_when(
    context: dict[str, Any],
    expression: str,
    target_step_id: Optional[str] = None
) -> bool:
    """Evaluate Jinja2 when expression."""
    scope = dict(context)
    if target_step_id:
        scope["call"] = get_call_buffer(context, target_step_id)
    
    env = Environment(autoescape=False)
    template = env.from_string("{{ " + expression + " }}")
    result = template.render(**scope)
    
    return bool(result and str(result).lower() not in ("false", "0", ""))


def call_step(context: dict[str, Any], target_id: str) -> None:
    """Dispatch or park step for execution."""
    step_def = get_step_definition(context, target_id)
    step_status = get_step_status(context, target_id)
    
    if step_status.get("done"):
        return  # idempotence
    
    # Evaluate when with call buffer
    when_expr = step_def.get("when")
    if when_expr and not eval_when(context, when_expr, target_id):
        mark_parked(context, target_id)
        return
    
    enqueue_for_execution(context, target_id)
```

---

**End of Document**

This implementation brief provides complete specification for the Edge args + Fan-out then features in NoETL DSL v2. All deliverables, acceptance criteria, and implementation details are documented for single-PR execution.

