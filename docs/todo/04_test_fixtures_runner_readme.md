# Test Fixtures, Runner Scaffolding, README Snippets

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Provide golden test fixtures, validation harness, runtime status tracking, and documentation snippets for DSL v2

---

## 4.1 Golden Fixtures (Valid)

**Location:** `tests/fixtures/workflows/v2/valid/`

---

### 4.1.1 Fan-Out AND-Join Pattern

**File:** `tests/fixtures/workflows/v2/valid/fanout_and_join.yaml`

```yaml
- step: start
  desc: "Entry"
  next:
    - step: fetch_user
    - step: score_user

- step: fetch_user
  desc: "Fetch user"
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "{{ api }}/users/{{ workload.user_id }}"
    result:
      as: user_raw
  next:
    - step: join

- step: score_user
  desc: "Score user"
  tool:
    kind: playbook
    spec:
      path: tests/fixtures/playbooks/user_scorer
    args:
      user: "{{ user_raw }}"
    result:
      as: user_score
  next:
    - step: join

- step: join
  desc: "Run only when both predecessors finished; proceed on success of scoring"
  when: "{{ done('fetch_user') and ok('score_user') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            u = context["user_raw"]; s = context["user_score"]
            return {"id": u["id"], "score": s["value"]}
    result:
      as: user_profile
      sink:
        - postgres:
            table: public.user_profiles
            mode: upsert
            key: id
            args:
              id: "{{ user_profile.id }}"
              score: "{{ user_profile.score }}"
  next:
    - step: done

- step: done
  desc: "Terminal step"
```

**Pattern highlights:**
- Fan-out: `start` → `fetch_user` + `score_user` (parallel)
- AND-join: `join` waits for both via `when: "{{ done('fetch_user') and ok('score_user') }}"`
- Result storage: `as` for context, `sink` for persistence
- Multi-sink capable (currently one postgres sink shown)

---

### 4.1.2 Loop with Collect and Reduce

**File:** `tests/fixtures/workflows/v2/valid/loop_reduce.yaml`

```yaml
- step: start
  next:
    - step: proc_users

- step: proc_users
  desc: "Loop over users as 'user'"
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  tool:
    kind: playbook
    spec:
      path: tests/fixtures/playbooks/user_profile_scorer
      return_step: finalize_result
    args:
      user_data: "{{ user }}"
    result:
      pick: "{{ {'name': user.name, 'score': this.profile_score or 0.0} }}"
      as: last_score
      collect:
        into: all_scores
        mode: list
      sink:
        - postgres:
            table: public.user_profile_results
            mode: upsert
            key: id
            args:
              id: "{{ execution_id }}:{{ out.name }}"
              score: "{{ out.score }}"
  next:
    - step: summarize

- step: summarize
  when: "{{ loop_done('proc_users') }}"
  tool:
    kind: workbook
    spec:
      name: summarize_scores
    args:
      scores: "{{ all_scores }}"
    result:
      as: summary
```

**Pattern highlights:**
- Parallel loop with `mode: parallel`
- `result.pick` transforms raw result before storage
- `result.collect.into: all_scores` accumulates all loop results
- `loop_done()` helper waits for full loop drain
- Fan-out to both context (`as`) and sink (postgres)

---

### 4.1.3 Simple HTTP with File Sink

**File:** `tests/fixtures/workflows/v2/valid/http_simple.yaml`

```yaml
- step: get_one
  desc: "Fetch single profile"
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "{{ base }}/users/{{ workload.user_id }}"
      headers:
        Authorization: "{{ secrets.api_token }}"
    result:
      sink:
        - file:
            path: "/tmp/user_{{ workload.user_id }}.json"
```

**Pattern highlights:**
- Minimal valid workflow (single step)
- HTTP with headers (auth token from secrets)
- File sink without context storage (write-only)
- No `next` (terminal step)

---

## 4.2 Negative Fixtures (Invalid)

**Location:** `tests/fixtures/workflows/v2/invalid/`

These fixtures **must fail** schema validation and/or semantic linting.

---

### 4.2.1 Extra Top-Level Keys

**File:** `tests/fixtures/workflows/v2/invalid/bad_top_level_keys.yaml`

```yaml
- step: bad1
  description: "wrong key 'description' instead of desc"
  args: { should_be_under_tool: true }
  tool:
    kind: http
    spec: { method: GET, endpoint: "/ok" }
```

**Expected failures:**
- Schema: `additionalProperties` violation (description, args)
- Lint: Extra keys not in `{step, desc, when, bind, loop, tool, next}`

---

### 4.2.2 Forbidden Iterator Tool

**File:** `tests/fixtures/workflows/v2/invalid/iterator_as_tool.yaml`

```yaml
- step: wrong
  tool: iterator
  collection: "{{ items }}"
  element: item
```

**Expected failures:**
- Schema: `tool` must be object with `kind` and `spec`
- Lint: "tool: iterator is invalid; use step.loop"

---

### 4.2.3 Multiple Else Edges

**File:** `tests/fixtures/workflows/v2/invalid/bad_next_shape.yaml`

```yaml
- step: branching
  tool:
    kind: python
    spec: { code: "def main(context, results): return {}" }
  next:
    - when: "{{ true }}"
      step: A
    - step: B
    - step: C      # second else -> lint should fail
```

**Expected failures:**
- Lint: "next may contain at most one edge without 'when' (else)"

---

### 4.2.4 Sink Not a List

**File:** `tests/fixtures/workflows/v2/invalid/sink_not_list.yaml`

```yaml
- step: save_wrong
  tool:
    kind: python
    spec: { code: "def main(context, results): return 1" }
    result:
      sink:
        postgres:
          table: t         # must be a list of single-key maps
```

**Expected failures:**
- Schema: `result.sink` must be array
- Lint: "result.sink must be a list"

---

### 4.2.5 Reserved Namespace Violation

**File:** `tests/fixtures/workflows/v2/invalid/reserved_namespace.yaml`

```yaml
- step: bad_bind
  bind:
    step: "attempt to write reserved namespace"
  tool:
    kind: python
    spec: { code: "def main(context, results): return 1" }
```

**Expected failures:**
- Lint: "bind.step is reserved and cannot be set by authors"

---

### 4.2.6 Invalid Collect Mode

**File:** `tests/fixtures/workflows/v2/invalid/bad_collect.yaml`

```yaml
- step: bad_collect
  loop:
    collection: "{{ items }}"
    element: item
  tool:
    kind: python
    spec: { code: "def main(context, results): return item" }
    result:
      collect:
        into: results
        mode: map        # mode: map requires key
```

**Expected failures:**
- Schema: `collect.mode: map` requires `collect.key`

---

## 4.3 PyTest Harness (Schema + Lint)

**File:** `tests/test_dsl_v2_validation.py`

```python
"""
DSL v2 Validation Test Suite

Tests schema validation and semantic linting against golden and negative fixtures.
Ensures valid fixtures pass and invalid fixtures fail as expected.
"""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
VAL = ROOT / "scripts" / "validate_dsl_v2.py"
LINT = ROOT / "scripts" / "lint_dsl_v2.py"

def run(cmd):
    """Run command and return exit code + output"""
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr

def test_valid_fixtures_pass_schema():
    """All valid fixtures must pass JSON Schema validation"""
    paths = list((ROOT / "tests" / "fixtures" / "workflows" / "v2" / "valid").glob("*.yaml"))
    assert paths, "No valid fixtures found"
    
    rc, out = run([sys.executable, str(VAL), *map(str, paths)])
    assert rc == 0, f"Schema validation failed for valid fixtures:\n{out}"

def test_valid_fixtures_pass_lint():
    """All valid fixtures must pass semantic linting"""
    paths = list((ROOT / "tests" / "fixtures" / "workflows" / "v2" / "valid").glob("*.yaml"))
    assert paths, "No valid fixtures found"
    
    rc, out = run([sys.executable, str(LINT), *map(str, paths)])
    assert rc == 0, f"Lint failed for valid fixtures:\n{out}"

def test_invalid_fixtures_fail_validation():
    """All invalid fixtures must fail schema validation or lint"""
    paths = list((ROOT / "tests" / "fixtures" / "workflows" / "v2" / "invalid").glob("*.yaml"))
    assert paths, "No invalid fixtures found"
    
    # At least one of schema or lint should fail
    rc_schema, out_schema = run([sys.executable, str(VAL), *map(str, paths)])
    rc_lint, out_lint = run([sys.executable, str(LINT), *map(str, paths)])
    
    assert rc_schema != 0 or rc_lint != 0, \
        "Invalid fixtures should fail validation or lint"

def test_invalid_fixtures_fail_lint():
    """All invalid fixtures must fail semantic linting"""
    paths = list((ROOT / "tests" / "fixtures" / "workflows" / "v2" / "invalid").glob("*.yaml"))
    assert paths, "No invalid fixtures found"
    
    rc, out = run([sys.executable, str(LINT), *map(str, paths)])
    assert rc != 0, f"Lint should fail for invalid fixtures:\n{out}"

def test_bad_top_level_keys_detected():
    """Specific test: extra keys at step level are rejected"""
    path = ROOT / "tests" / "fixtures" / "workflows" / "v2" / "invalid" / "bad_top_level_keys.yaml"
    if not path.exists():
        return  # Skip if fixture not created yet
    
    rc, out = run([sys.executable, str(LINT), str(path)])
    assert rc != 0
    assert "top-level keys must be" in out or "Additional properties" in out

def test_iterator_as_tool_detected():
    """Specific test: tool: iterator is rejected"""
    path = ROOT / "tests" / "fixtures" / "workflows" / "v2" / "invalid" / "iterator_as_tool.yaml"
    if not path.exists():
        return
    
    rc, out = run([sys.executable, str(LINT), str(path)])
    assert rc != 0
    assert "tool: iterator" in out or "use step.loop" in out

def test_multiple_else_edges_detected():
    """Specific test: multiple next edges without when are rejected"""
    path = ROOT / "tests" / "fixtures" / "workflows" / "v2" / "invalid" / "bad_next_shape.yaml"
    if not path.exists():
        return
    
    rc, out = run([sys.executable, str(LINT), str(path)])
    assert rc != 0
    assert "at most one" in out and "else" in out

def test_sink_not_list_detected():
    """Specific test: sink as object instead of list is rejected"""
    path = ROOT / "tests" / "fixtures" / "workflows" / "v2" / "invalid" / "sink_not_list.yaml"
    if not path.exists():
        return
    
    rc, out = run([sys.executable, str(VAL), str(path)])
    assert rc != 0
    # Schema should fail: sink must be array

def test_reserved_namespace_detected():
    """Specific test: bind.step is rejected"""
    path = ROOT / "tests" / "fixtures" / "workflows" / "v2" / "invalid" / "reserved_namespace.yaml"
    if not path.exists():
        return
    
    rc, out = run([sys.executable, str(LINT), str(path)])
    assert rc != 0
    assert "bind.step is reserved" in out
```

**Run tests:**
```bash
pytest tests/test_dsl_v2_validation.py -v
```

---

## 4.4 Minimal Runner Hooks (Status + Helpers)

**Purpose:** Runtime status tracking for engine helpers (`done()`, `ok()`, etc.)

**File:** `noetl/runtime/status.py`

```python
"""
Runtime Status Tracking

Provides step status management for DSL v2 execution engine.
Status structure: context["step"][step_id]["status"] = {
    "running": bool,
    "done": bool,
    "ok": bool | None,
    "error": str | None,
    "total": int | None,        # Loop only
    "completed": int,           # Loop only
    "succeeded": int,           # Loop only
    "failed": int               # Loop only
}

Used by Jinja helpers (done(), ok(), fail(), running(), loop_done())
"""

def mark_start(ctx, sid, total=None):
    """
    Mark step as started.
    
    Args:
        ctx: Execution context dict
        sid: Step ID
        total: Optional total items for loop (enables loop tracking)
    
    Returns:
        Modified context
    """
    node = ctx.setdefault("step", {}).setdefault(sid, {})
    st = node.setdefault("status", {})
    st.update({"running": True, "done": False, "ok": None})
    
    if total is not None:
        st.update({
            "total": int(total),
            "completed": 0,
            "succeeded": 0,
            "failed": 0
        })
    
    return ctx

def mark_item_done(ctx, sid, ok=True):
    """
    Mark one loop item as completed.
    
    Args:
        ctx: Execution context dict
        sid: Step ID
        ok: Whether item succeeded
    
    Updates completed, succeeded, or failed counters.
    """
    st = ctx["step"][sid]["status"]
    st["completed"] = st.get("completed", 0) + 1
    
    if ok:
        st["succeeded"] = st.get("succeeded", 0) + 1
    else:
        st["failed"] = st.get("failed", 0) + 1

def mark_finish(ctx, sid, ok=True, error=None):
    """
    Mark step as finished.
    
    Args:
        ctx: Execution context dict
        sid: Step ID
        ok: Whether step succeeded
        error: Optional error message if failed
    
    Returns:
        Modified context
    """
    st = ctx["step"][sid]["status"]
    st.update({
        "running": False,
        "done": True,
        "ok": bool(ok)
    })
    
    if error:
        st["error"] = str(error)
    
    return ctx

def get_status(ctx, sid):
    """
    Get step status dict.
    
    Args:
        ctx: Execution context dict
        sid: Step ID
    
    Returns:
        Status dict or empty dict if not found
    """
    return ctx.get("step", {}).get(sid, {}).get("status", {})
```

---

### Integration Example

**In execution engine:**

```python
from noetl.runtime.status import mark_start, mark_item_done, mark_finish
from scripts.jinja_helpers import install_helpers
from jinja2 import Environment

class WorkflowExecutor:
    def __init__(self):
        self.context = {"step": {}}
        self.env = Environment()
        install_helpers(self.env, lambda: self.context)
    
    def execute_step(self, step_id, step_config):
        """Execute a single step"""
        # Mark start
        mark_start(self.context, step_id)
        
        try:
            # Execute tool
            result = self.run_tool(step_config["tool"])
            
            # Mark success
            mark_finish(self.context, step_id, ok=True)
        except Exception as e:
            # Mark failure
            mark_finish(self.context, step_id, ok=False, error=str(e))
    
    def execute_loop_step(self, step_id, step_config):
        """Execute a step with loop"""
        collection = self.render(step_config["loop"]["collection"])
        items = list(collection)
        
        # Mark start with total
        mark_start(self.context, step_id, total=len(items))
        
        for item in items:
            try:
                result = self.run_tool_with_element(step_config["tool"], item)
                mark_item_done(self.context, step_id, ok=True)
            except Exception:
                mark_item_done(self.context, step_id, ok=False)
        
        # Mark finish
        mark_finish(self.context, step_id, ok=True)
    
    def evaluate_when(self, when_expr):
        """Evaluate when condition with helpers"""
        template = self.env.from_string(when_expr)
        return template.render(**self.context)
```

---

## 4.5 README Snippets

Drop-in sections for main README.md documentation.

---

### 4.5.1 Workflow Step Schema (v2)

```markdown
## Workflow Step Schema (v2)

Top-level keys (exactly 4 chars): `step, desc, when, bind, loop, tool, next`.

### Core Fields

- **`step`** (required): Unique step identifier
- **`desc`**: Human-readable description
- **`when`**: Gate condition (evaluated on each call)
- **`bind`**: Extra context bindings

### Loop Controller

- **`loop`**: Iteration controller
  - `collection`: Jinja expression yielding iterable
  - `element`: Variable name for each item
  - `mode`: `sequential` | `parallel` (default: sequential)
  - `until`: Optional exit condition

### Tool Configuration

- **`tool`**: Actionable unit
  - `kind`: Plugin ID (`http`, `postgres`, `python`, `duckdb`, `playbook`, `workbook`, ...)
  - `spec`: Per-plugin contract (e.g., `path` for playbook, `method` for http)
  - `args`: Inputs to the plugin
  - `result`: Handling of plugin output
    - `as`: Store shaped result in context
    - `pick`: Transform `this` → `out` (Jinja expression)
    - `sink`: **List** of single-key objects (fan-out destinations)
    - `collect`: Loop accumulator `{ into, mode: list|map, key? }`

### Routing

- **`next`**: Ordered list of edges `{ step, when? }`
  - First matching edge is taken
  - One item may omit `when` (else-fallthrough)
  - Evaluated in order (if/elif/else semantics)

### Example

```yaml
- step: process_users
  desc: "Process all users in parallel"
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  tool:
    kind: playbook
    spec:
      path: playbooks/user_processor
    args:
      user_data: "{{ user }}"
    result:
      as: last_result
      collect:
        into: all_results
        mode: list
      sink:
        - postgres:
            table: processed_users
            key: id
  next:
    - when: "{{ loop_done('process_users') }}"
      step: summarize
```
```

---

### 4.5.2 Petri-Net Semantics

```markdown
## Petri-Net Semantics

NoETL workflows follow Petri-net execution model:

### Calling Model

- Only `start` step is enabled initially
- All other steps run **only when called** via `next` edges
- On **each call**, the target step evaluates its **step-level `when`**:
  - If `false` → parked; future calls re-evaluate
  - When `true` → executes **once** (idempotent)

### Execution Flow

1. **Start step** executes automatically
2. Evaluates `next` edges to find targets
3. **Calls** target steps (may queue multiple)
4. Each target evaluates its `when` condition
5. If `when` is true (or omitted), step executes
6. On completion, evaluates its own `next` edges
7. Process repeats until no more calls

### Parallelism

- Use `loop.mode: parallel` for fan-out within a step
- Use multiple `next` targets for graph-level parallelism
- Steps called in parallel may execute concurrently (worker pool)

### Engine Helpers

Use these in `when` conditions to coordinate steps:

- `done('step_id')`: Step has completed (success or failure)
- `ok('step_id')`: Step succeeded
- `fail('step_id')`: Step failed
- `running('step_id')`: Step is currently executing
- `loop_done('step_id')`: Loop has fully drained
- `all_done(['id1', 'id2', ...])`: All steps done
- `any_done(['id1', 'id2', ...])`: At least one step done

### Example: AND-Join

```yaml
- step: join
  desc: "Wait for both A and B to finish; require B success"
  when: "{{ done('step_a') and ok('step_b') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {"combined": context["step_a_result"] + context["step_b_result"]}
```
```

---

### 4.5.3 Result Handling

```markdown
## Result Handling

Tool execution follows a deterministic pipeline:

### Pipeline Steps

1. **Tool returns `this`** (raw result from plugin)
2. **If `result.pick`** → compute `out = pick(this, context)`; else `out = this`
3. **If `result.as`** → store `context[as] = out`
4. **If `result.collect`** (in a loop) → append/merge `out` into `context[collect.into]`
5. **For every entry in `result.sink`** → write `out` to that destination

### Examples

**Store in context only:**
```yaml
result:
  as: user_data
```

**Transform before storing:**
```yaml
result:
  pick: "{{ {'id': this.user_id, 'name': this.full_name} }}"
  as: user_profile
```

**Fan-out to multiple sinks:**
```yaml
result:
  sink:
    - postgres:
        table: users
        key: id
    - s3:
        bucket: data-lake
        key: "users/{{ execution_id }}.json"
```

**Collect loop results:**
```yaml
loop:
  collection: "{{ workload.items }}"
  element: item
tool:
  kind: python
  spec:
    code: |
      def main(context, results):
          return {"processed": item["value"] * 2}
  result:
    collect:
      into: all_processed
      mode: list
```

**Collect as map:**
```yaml
result:
  collect:
    into: user_scores
    mode: map
    key: "{{ out.user_id }}"
```
```

---

### 4.5.4 Do/Don't

```markdown
## Do/Don't

### Do ✓

- Keep step keys to 4 chars: `{step, desc, when, bind, loop, tool, next}`
- Put all plugin config under `tool.spec`
- Use `loop` at step level for iteration
- Use `result.sink` (list) for persistence
- Use engine helpers for coordination: `done()`, `ok()`, `loop_done()`
- Put at most one `next` edge without `when` (else-fallthrough)
- Use single-key maps in `result.sink`: `[{postgres: {...}}, {s3: {...}}]`

### Don't ✗

- Don't use `tool: iterator` (removed in v2)
- Don't place `args` or `save` at step level (move under `tool`)
- Don't write into the reserved `step.*` namespace
- Don't have more than one `next` edge without `when`
- Don't use legacy aliases: `iter`, `iterator`, `over`, `coll`
- Don't nest `task:` objects (flatten into `tool` structure)
- Don't use `result.sinks` (plural) - use `result.sink` (singular, list)

### Migration from v1

If you have legacy playbooks:

```bash
# Run codemod
python scripts/codemod_dsl_v2.py your_playbook.yaml

# Validate
python scripts/validate_dsl_v2.py your_playbook.yaml
python scripts/lint_dsl_v2.py your_playbook.yaml
```
```

---

## 4.6 Quick Lint Targets (package.json Optional)

If using npm scripts for tooling:

**File:** `package.json` (add to existing or create new)

```json
{
  "name": "noetl",
  "version": "2.0.0",
  "scripts": {
    "dsl:validate": "python scripts/validate_dsl_v2.py tests/fixtures/workflows/v2/**/*.yaml",
    "dsl:lint": "python scripts/lint_dsl_v2.py tests/fixtures/workflows/v2/**/*.yaml",
    "dsl:test": "pytest tests/test_dsl_v2_validation.py -v",
    "dsl:all": "npm run dsl:validate && npm run dsl:lint && npm run dsl:test",
    "dsl:codemod": "python scripts/codemod_dsl_v2.py"
  }
}
```

**Usage:**
```bash
# Validate all fixtures
npm run dsl:validate

# Lint all fixtures
npm run dsl:lint

# Run full test suite
npm run dsl:test

# Run all checks
npm run dsl:all

# Run codemod on specific files
npm run dsl:codemod -- examples/**/*.yaml
```

**Alternative (Makefile):**

```makefile
.PHONY: dsl-validate dsl-lint dsl-test dsl-all

dsl-validate:
	python scripts/validate_dsl_v2.py tests/fixtures/workflows/v2/**/*.yaml

dsl-lint:
	python scripts/lint_dsl_v2.py tests/fixtures/workflows/v2/**/*.yaml

dsl-test:
	pytest tests/test_dsl_v2_validation.py -v

dsl-all: dsl-validate dsl-lint dsl-test
	@echo "All DSL v2 checks passed"
```

---

## 4.7 Author Cheat Sheet

**Add to README.md or create `docs/dsl_cheatsheet.md`**

```markdown
# DSL v2 Cheat Sheet

Quick reference for common patterns.

## Core Structure

```yaml
- step: step_id
  desc: "Description"
  when: "{{ condition }}"
  bind: { key: "{{ value }}" }
  loop: { collection: "{{ items }}", element: item, mode: parallel }
  tool: { kind: plugin_id, spec: {...}, args: {...}, result: {...} }
  next: [ { when: "{{ cond }}", step: target } ]
```

## Common Patterns

### Loop
```yaml
loop:
  collection: "{{ workload.items }}"
  element: item
  mode: parallel  # or sequential
```

### Save Variable to Context
```yaml
tool:
  result:
    as: last_item
```

### Fan-Out to Multiple Sinks
```yaml
tool:
  result:
    sink:
      - postgres: { table: users, key: id }
      - s3: { bucket: data-lake, key: "users.json" }
```

### AND-Join (Wait for Multiple Steps)
```yaml
when: "{{ done('step_a') and ok('step_b') }}"
```

### Else Edge (Fallthrough)
```yaml
next:
  - when: "{{ score > 80 }}"
    step: high_score
  - when: "{{ score > 50 }}"
    step: medium_score
  - step: low_score  # Else (no when)
```

### Transform Result
```yaml
tool:
  result:
    pick: "{{ {'id': this.user_id, 'score': this.raw_score * 100} }}"
    as: processed
```

### Collect Loop Results (List)
```yaml
tool:
  result:
    collect:
      into: all_results
      mode: list
```

### Collect Loop Results (Map)
```yaml
tool:
  result:
    collect:
      into: user_map
      mode: map
      key: "{{ out.user_id }}"
```

## Engine Helpers

Use in `when` conditions:

| Helper | Description |
|--------|-------------|
| `done('step_id')` | Step completed (success or failure) |
| `ok('step_id')` | Step succeeded |
| `fail('step_id')` | Step failed |
| `running('step_id')` | Step is currently running |
| `loop_done('step_id')` | Loop fully drained |
| `all_done(['a', 'b'])` | All steps done |
| `any_done(['a', 'b'])` | Any step done |

## Plugin Quick Reference

### HTTP
```yaml
tool:
  kind: http
  spec:
    method: GET|POST|PUT|DELETE
    endpoint: "{{ url }}"
    headers: { Authorization: "{{ token }}" }
    params: { limit: 10 }
    payload: { key: "{{ value }}" }
```

### Postgres
```yaml
tool:
  kind: postgres
  spec:
    query: "SELECT * FROM users WHERE id = {{ user_id }}"
    auth: { credential: pg_cred }
    params: { id: "{{ user_id }}" }
```

### Python
```yaml
tool:
  kind: python
  spec:
    code: |
      def main(context, results):
          return {"result": context["input"] * 2}
```

### DuckDB
```yaml
tool:
  kind: duckdb
  spec:
    query: "SELECT * FROM read_csv('{{ file }}')"
    file: "./data.duckdb"
```

### Playbook (Call Sub-Workflow)
```yaml
tool:
  kind: playbook
  spec:
    path: playbooks/user_processor
    entry_step: start  # Optional
    return_step: done  # Optional
  args:
    user_data: "{{ user }}"
```

### Workbook (Call Named Task)
```yaml
tool:
  kind: workbook
  spec:
    name: task_name
  args:
    input: "{{ data }}"
```

## Migration from v1

### Old (v1)
```yaml
- step: proc
  tool: iterator
  collection: "{{ items }}"
  element: item
  args: { query: "SELECT *" }
  save: { storage: postgres, table: results }
```

### New (v2)
```yaml
- step: proc
  loop:
    collection: "{{ items }}"
    element: item
  tool:
    kind: postgres
    spec: { query: "SELECT *" }
    args: {}
    result:
      sink:
        - postgres: { table: results }
```

## Validation

```bash
# Schema check
python scripts/validate_dsl_v2.py playbook.yaml

# Semantic lint
python scripts/lint_dsl_v2.py playbook.yaml

# Auto-fix (codemod)
python scripts/codemod_dsl_v2.py playbook.yaml
```
```

---

## 4.8 Directory Structure Summary

```
noetl/
├── scripts/
│   ├── workflow-steps.v2.json       # JSON Schema
│   ├── validate_dsl_v2.py           # Schema validator
│   ├── lint_dsl_v2.py               # Semantic linter
│   ├── codemod_dsl_v2.py            # Auto-migration tool
│   └── jinja_helpers.py             # Engine status helpers
├── noetl/
│   └── runtime/
│       └── status.py                 # Status tracking
├── tests/
│   ├── fixtures/
│   │   └── workflows/
│   │       └── v2/
│   │           ├── valid/
│   │           │   ├── fanout_and_join.yaml
│   │           │   ├── loop_reduce.yaml
│   │           │   └── http_simple.yaml
│   │           └── invalid/
│   │               ├── bad_top_level_keys.yaml
│   │               ├── iterator_as_tool.yaml
│   │               ├── bad_next_shape.yaml
│   │               ├── sink_not_list.yaml
│   │               ├── reserved_namespace.yaml
│   │               └── bad_collect.yaml
│   └── test_dsl_v2_validation.py    # PyTest suite
├── docs/
│   ├── dsl_cheatsheet.md            # Quick reference
│   └── todo/
│       ├── 01_dsl_refactoring_overview.md
│       ├── 02_migration_strategy_and_codemods.md
│       ├── 03_schema_validation_and_linter.md
│       └── 04_test_fixtures_runner_readme.md
├── .vscode/
│   └── tasks.json                    # VS Code tasks
├── package.json                      # npm scripts (optional)
└── Makefile                          # Make targets (optional)
```

---

## Next Steps

This document provides **test fixtures, validation harness, runtime hooks, and documentation**. Next portions will cover:

1. **Engine Implementation**: Core execution engine changes to support new DSL features
2. **Plugin Refactoring**: Adapter layer for plugins to consume new tool structure
3. **E2E Testing**: Integration tests with full execution pipeline

---

**Ready for next portion of the refactoring plan.**
