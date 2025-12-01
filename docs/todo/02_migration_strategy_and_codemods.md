# DSL Migration Strategy & Codemods

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Define migration path from current DSL to refactored 4-key canonical surface

---

## A. What We're Migrating From → To (Field Mapping)

### Step-Level (4-Char Keys Enforced)

| Key | Migration Status | Details |
|-----|------------------|---------|
| `step` | ✓ Unchanged | Unique step identifier |
| `desc` | ✓ Unchanged | Human-readable description |
| `when` | ✓ Semantics clarified | Gate on call (evaluated when step is called) |
| `bind` | ✓ Unchanged | Extra context bindings |

### Loop Migration

**From:** Multiple aliases and scattered fields
```yaml
# Old (various forms)
iterator: ...
iter: ...
over: ...
collection: "{{ workload.users }}"
element: user
mode: sequential
```

**To:** Unified `loop` block
```yaml
loop:
  collection: "{{ workload.users }}"
  element: user
  mode: sequential        # Optional (default: sequential)
  until: "{{ condition }}" # Optional
```

**Aliases to remove:** `iterator`, `iter`, `over`, `coll`

---

### Tool Migration

**From:** Mixed representations
```yaml
# Various old forms:
tool: iterator                    # Special type (remove)
tool: workbook                    # Scalar
tool: playbook                    # Scalar
task:                             # Nested blob
  tool: playbook
  path: ...
  args: ...
  sink: ...

# Step-level args/save
args: { ... }
sink: { tool: postgres, ... }
```

**To:** Normalized structure
```yaml
tool:
  kind: <plugin_id>               # playbook | workbook | http | postgres | python | duckdb
  spec: { ... }                   # Per-plugin configuration
  args: { ... }                   # Moved from step-level
  result:                         # Replaces step-level save
    as: <context_key>             # Optional: store result
    pick: <jinja_expr>            # Optional: transform result
    sink:                         # List of sinks (replaces save)
      - <sink_id>:
          table: ...
          key: ...
          args: ...
    collect:                      # Optional: accumulate in loops
      into: <context_key>
      mode: list|map              # Default: list
      key: <jinja_expr>           # Required if mode=map
```

**Key Changes:**
- `args` moves from step-level to `tool.args`
- `save` becomes `tool.result.sink` (list format)
- Add new capabilities: `as`, `pick`, `collect`

---

### Next Migration

**From:** Mixed formats
```yaml
# Scalar
next: some_step

# Mixed
next:
  - when: "{{ condition }}"
    then: step_a
  - step_b

# Object with 'then' key
next:
  - when: "{{ x > 5 }}"
    then:
      - step: target
```

**To:** Uniform array of objects
```yaml
next:
  - when: "{{ condition }}"       # Optional (if/elif)
    step: target_step_id
  - step: else_target             # Final else (no when)
```

**Rules:**
- Always an array
- Each entry is `{ step: <id>, when?: <expr> }`
- Ordered if/elif/else evaluation
- At most one entry without `when` (final else)

---

### Special Removals / Rewrites

| Old Pattern | New Pattern | Action |
|-------------|-------------|--------|
| `tool: iterator` | `loop: { ... }` at step level | Remove `tool: iterator`, create/merge `loop` block |
| Nested `task:` blobs | Flatten into `tool` block | Promote task config to tool |
| Step-level `save` | `tool.result.sink` (list) | Convert to list of single-key maps |
| Step-level `args` | `tool.args` | Move under tool |
| Non-4-char keys | Move to `tool.spec` or remove | Enforce canonical keys |

---

### Engine Helpers (No Authoring Change)

Add Jinja global functions (available in templates):

```python
done(step_id)           # Step completed
ok(step_id)             # Step succeeded
fail(step_id)           # Step failed
running(step_id)        # Step is running
loop_done(step_id)      # Loop fully drained
all_done([ids])         # All steps done
any_done([ids])         # Any step done
```

---

## B. Migration Phases (Safe Rollout)

### Phase 1: Lint-Only Pass
**Goal:** Detect incompatible constructs without changing files

**Actions:**
- Run linter on all playbooks
- Generate violation reports
- No file modifications

**Output:** List of files requiring migration + specific violations

---

### Phase 2: Codemod Pass
**Goal:** Mechanical rewrites (idempotent)

**Actions:**
- Apply automated transformations
- Preserve semantics
- Format-preserving where possible
- Idempotent (safe to re-run)

**Transforms:**
1. Normalize iteration (aliases → `loop`)
2. Remove nested `task:` blobs
3. Move step-level `args`/`save` under `tool`
4. Normalize `next` to array format
5. Build `tool` block structure
6. Enforce 4-char top-level keys

---

### Phase 3: Semantic Upgrade Pass
**Goal:** Introduce new capabilities where helpful

**Actions:**
- Add `result.as` for context storage
- Add `result.collect.into` for loop accumulation
- Optimize `result.pick` for transformations
- Manual review recommended

**Output:** Enhanced playbooks with new DSL features

---

### Phase 4: Validation
**Goal:** Ensure compliance with new schema

**Actions:**
- Run JSON Schema validation
- Run custom lints
- Block on violations
- Generate compliance report

**Checks:**
- All steps use 4-char keys only
- No legacy aliases (`iter`, `iterator`, etc.)
- All `tool` blocks properly structured
- All `next` entries are objects
- All `sink` entries are single-key maps

---

### Phase 5: Fixture Update
**Goal:** Rewrite examples and tests

**Actions:**
- Apply codemods to `examples/`
- Apply codemods to `tests/fixtures/`
- Run unit tests
- Run e2e tests
- Fix any broken tests

---

### Phase 6: Documentation
**Goal:** Update all documentation

**Actions:**
- Update `README.md`
- Update `docs/` guides
- Update code samples
- Add migration guide
- Update `CHANGELOG.md`

---

### Branch Strategy

**Main branch:** `refactor/dsl-v2-surface`

**Requirements:**
- All codemods must be reversible
- Format-preserving transformations preferred
- Tag before major changes: `pre-dsl-v2`

---

## C. Lints (Pre-Codemod)

### Critical Failures (Block Migration)

**Fail if found:**

1. ❌ **`tool: iterator`**
   ```yaml
   # ERROR: Must be converted to loop block
   tool: iterator
   ```

2. ❌ **Step-level `args:` or `sink:`**
   ```yaml
   # ERROR: Must move under tool
   args: { ... }
   sink: { ... }
   ```

3. ❌ **Nested `task:` object**
   ```yaml
   # ERROR: Must flatten into tool
   task:
     tool: playbook
     path: ...
   ```

4. ❌ **`next:` not an array**
   ```yaml
   # ERROR: Must be array format
   next: some_step
   ```

5. ❌ **Non-4-char top-level keys at step**
   ```yaml
   # ERROR: Only {step,desc,when,bind,loop,tool,next} allowed
   step: foo
   method: GET        # ERROR: must be under tool.spec
   endpoint: ...      # ERROR: must be under tool.spec
   ```

6. ❌ **Both `loop` and alias present**
   ```yaml
   # ERROR: Conflicting iteration configs
   loop: { ... }
   iter: { ... }      # ERROR: remove alias
   ```

7. ❌ **`tool.result.sink` not a list**
   ```yaml
   # ERROR: sink must be list of single-key maps
   tool:
     result:
       sink: { postgres: ... }  # ERROR: wrap in array
   ```

---

### Warnings (Auto-Fixable)

**Warn (will be auto-fixed by codemod):**

1. ⚠️ **Iteration aliases** → `loop`
   ```yaml
   # Warn: Will convert to loop
   iter: { collection: "{{ users }}", element: user }
   iterator: ...
   over: ...
   coll: ...
   ```

2. ⚠️ **`result.sinks` (plural)** → `result.sink`
   ```yaml
   # Warn: Will rename to sink
   result:
     sinks: [ ... ]   # Will become: sink
   ```

3. ⚠️ **Scalar `tool: workbook`** → Wrap in structure
   ```yaml
   # Warn: Will wrap into tool block
   tool: workbook     # Will become: tool: { kind: workbook, spec: { name: ... } }
   ```

4. ⚠️ **Scalar `tool: playbook`** → Wrap in structure
   ```yaml
   # Warn: Will wrap into tool block
   tool: playbook     # Will become: tool: { kind: playbook, spec: { path: ... } }
   ```

---

## D. Codemod Rules (Mechanical Transforms)

**Apply in order; each transform is idempotent.**

---

### Rule 1: Normalize Iteration

**Detect:** Step has any of `iterator`, `iter`, `over`, `coll` at top-level

**Transform:**
1. Create `loop` block if missing
2. Move `collection`, `element`, `mode`, `until` under `loop`
3. Delete alias keys

**Special case:** If step has `tool: iterator`:
- **Error:** Cannot keep this form
- **Rewrite:**
  1. Create/merge `loop` from adjacent `collection|element|mode|until`
  2. Remove `tool: iterator`
  3. If nested `task` exists, promote it into `tool` (see Rule 2)

**Example:**
```yaml
# Before
- step: proc_users
  tool: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: parallel

# After
- step: proc_users
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  # tool will be added by task promotion if exists
```

---

### Rule 2: Remove Nested `task:` Blobs

**Detect:** Step contains `task:` key

**Transform:**

```yaml
# Before
task:
  task: <alias>              # Discard or map to result.as if needed
  tool: <PLUGIN>             # → kind
  path: ...                  # → spec.path
  name: ...                  # → spec.name
  args: { ... }              # → tool.args
  sink: { ... }              # → tool.result.sink

# After
tool:
  kind: <resolved plugin id>      # playbook|workbook|http|postgres|...
  spec:
    path: ...                     # If kind=playbook
    name: ...                     # If kind=workbook
    # ... other plugin-specific fields
  args: { ... }
  result:
    sink:
      - <sink_id>:
          ... # Migrated from save
```

**Plugin-specific mappings:**
- `tool: playbook` + `path:` → `kind: playbook`, `spec.path = path`
- `tool: workbook` + `name:` → `kind: workbook`, `spec.name = name`
- `tool: http` → `kind: http`, move `method`, `endpoint`, `headers`, etc. to `spec`
- `tool: postgres` → `kind: postgres`, move `query`, `auth`, `params` to `spec`

---

### Rule 3: Move Step-Level `args` / `save` Under `tool`

**Detect:** Step has `args` or `save` at top level

**Transform:**

**For `args`:**
```yaml
# Before
step: load_data
tool: postgres
args: { query: "SELECT * FROM users" }

# After
step: load_data
tool:
  kind: postgres
  spec: {}
  args: { query: "SELECT * FROM users" }
```

**For `save` (single map):**
```yaml
# Before
sink:
  tool: postgres
  table: users
  key: id

# After
tool:
  result:
    sink:
      - postgres:
          table: users
          key: id
```

**Sink ID normalization:**
- Prefer the key as sink ID
- Remove redundant `storage` field if sink infers it from key
- Common sinks: `postgres`, `duckdb`, `http`, `s3`, `gcs`, `file`, `kafka`

**For `save` (list):**
```yaml
# Before
sink:
  - { tool: postgres, table: users }
  - { tool: duckdb, file: ./out.db }

# After
tool:
  result:
    sink:
      - postgres: { table: users }
      - duckdb: { file: ./out.db }
```

---

### Rule 4: Normalize `next`

**Detect:** `next` is string or has mixed scalar/object entries

**Transform:**

**String to array:**
```yaml
# Before
next: some_step

# After
next:
  - step: some_step
```

**Mixed entries:**
```yaml
# Before
next:
  - some_step                        # Scalar
  - when: "{{ x > 5 }}"
    step: other_step                 # Object

# After
next:
  - step: some_step                  # Convert scalar to object
  - when: "{{ x > 5 }}"
    step: other_step
```

**Validation:**
- Ensure at most one item without `when` (final else)
- All `when` entries must come before the else entry

---

### Rule 5: Build `tool` Block When Only `tool: <id>` Present

**Detect:** `tool` is scalar and adjacent config keys exist (legacy)

**Transform:**
```yaml
# Before
step: fetch_data
tool: http
method: GET
endpoint: "{{ api_url }}/users"
headers:
  Authorization: "Bearer {{ token }}"

# After
step: fetch_data
tool:
  kind: http
  spec:
    method: GET
    endpoint: "{{ api_url }}/users"
    headers:
      Authorization: "Bearer {{ token }}"
```

**Move known plugin config keys into `spec`:**
- HTTP: `method`, `endpoint`, `headers`, `params`, `payload`
- Postgres: `query`, `auth`, `connection`, `params`
- DuckDB: `query`, `file`
- Playbook: `path`, `entry_step`, `return_step`
- Workbook: `name`
- Python: `code`, `module`, `callable`

---

### Rule 6: Optional Semantic Sugar

**Auto-apply where safe:**

**Single sink simplification:**
```yaml
# If step emits to a single sink and has matching fields
# Auto-key under that sink type and drop redundant storage

# Before
sink:
  tool: postgres
  table: users
  key: id

# After (implicit)
tool:
  result:
    sink:
      - postgres:
          table: users
          key: id
          # storage field removed (redundant)
```

**Loop collection naming:**
```yaml
# If step fans over collection and later step reads the whole set
# Add result.collect.into by convention

# Name: pluralize <element> or all_<alias> if conflict
# Example: element: user → into: users (if not already used)
#          element: item → into: all_items (if items exists)
```

---

## E. Codemod Outline (Python, YAML-Aware)

Create `scripts/codemod_dsl_v2.py`:

```python
import sys, yaml, copy, pathlib

# Alias mapping
ALIASES = {
    "iter": "loop",
    "iterator": "loop",
    "over": "loop",
    "coll": "loop"
}

def is_step(node):
    """Check if node is a step definition"""
    return isinstance(node, dict) and "step" in node

def normalize_loop(step):
    """
    Convert iteration aliases to unified loop block.
    Remove tool: iterator and promote nested config.
    """
    # Alias → loop
    for k in list(step.keys()):
        if k in ALIASES:
            step.setdefault("loop", {})
            v = step.pop(k)
            if isinstance(v, dict):
                # Merge safe keys
                for kk in ["collection", "element", "mode", "until"]:
                    if kk in v:
                        step["loop"][kk] = v[kk]
    
    # tool: iterator → loop + remove
    if step.get("tool") == "iterator":
        step.pop("tool")
        # Leave step["loop"] as constructed by previous pass

def normalize_tool(step):
    """
    Move step-level args/save into tool block.
    Convert save to result.sink list format.
    """
    # Step-level args → tool.args
    if "args" in step:
        step.setdefault("tool", {})
        step["tool"].setdefault("args", step.pop("args"))
    
    # Step-level save → tool.result.sink
    if "save" in step:
        save = step.pop("save")
        step.setdefault("tool", {})
        res = step["tool"].setdefault("result", {})
        sinks = res.setdefault("sink", [])
        
        # Wrap single sink; prefer key by storage
        if isinstance(save, dict):
            storage = save.get("storage", "postgres")
            sinks.append({storage: save})
        elif isinstance(save, list):
            for s in sink:
                sinks.append(s)
    
    # Scalar tool → object
    if isinstance(step.get("tool"), str):
        kind = step["tool"]
        step["tool"] = {"kind": kind, "spec": {}}
    
    # Nested task → tool
    if "task" in step:
        t = step.pop("task")
        
        # Promote into tool
        kind = t.get("tool") or t.get("kind")
        spec = {}
        
        # Plugin-specific spec migration
        if kind == "playbook":
            spec["path"] = t.get("path")
            if "entry_step" in t:
                spec["entry_step"] = t["entry_step"]
            if "return_step" in t:
                spec["return_step"] = t["return_step"]
        
        if kind == "workbook":
            spec["name"] = t.get("name")
        
        # Generic passthrough fields into spec
        for k in ["path", "name", "method", "endpoint", "query", 
                  "auth", "connection", "return_step", "entry_step",
                  "headers", "params", "payload", "file"]:
            if k in t:
                spec[k] = t[k]
        
        step["tool"] = {"kind": kind, "spec": spec}
        
        if "args" in t:
            step["tool"]["args"] = t["args"]
        
        if "save" in t:
            res = step["tool"].setdefault("result", {})
            storage = t["save"].get("storage", "postgres")
            res["sink"] = [{storage: t["save"]}]

def normalize_next(step):
    """
    Convert next to uniform array-of-objects format.
    Scalar → [{step: <id>}]
    Mixed → all objects
    """
    nxt = step.get("next")
    if nxt is None:
        return
    
    if isinstance(nxt, str):
        step["next"] = [{"step": nxt}]
    elif isinstance(nxt, list):
        out = []
        for it in nxt:
            if isinstance(it, str):
                out.append({"step": it})
            elif isinstance(it, dict) and "step" in it:
                out.append(it)
            elif isinstance(it, dict) and "then" in it:
                # Old format: {when: ..., then: ...}
                # Convert then to step
                when = it.get("when")
                then_val = it["then"]
                if isinstance(then_val, str):
                    entry = {"step": then_val}
                    if when:
                        entry["when"] = when
                    out.append(entry)
                elif isinstance(then_val, list):
                    # Nested list under then
                    for sub in then_val:
                        if isinstance(sub, dict) and "step" in sub:
                            entry = sub.copy()
                            if when and "when" not in entry:
                                entry["when"] = when
                            out.append(entry)
        step["next"] = out

def enforce_top_keys(step):
    """
    Enforce 4-char canonical keys at step level.
    Move plugin-specific keys into tool.spec if possible.
    """
    allowed = {"step", "desc", "when", "bind", "loop", "tool", "next"}
    
    for k in list(step.keys()):
        if k not in allowed:
            # Move plugin-ish keys into tool.spec if possible
            if k in ("method", "endpoint", "query", "path", "name",
                    "headers", "params", "payload", "auth", "connection",
                    "file", "table", "key", "mode"):
                step.setdefault("tool", {"kind": "http", "spec": {}})
                step["tool"].setdefault("spec", {})[k] = step.pop(k)
            else:
                # Leave unknown keys (or log warning)
                pass

def transform(doc):
    """
    Apply all transformation rules to document.
    Returns (modified_doc, changed_flag).
    """
    changed = False
    items = doc if isinstance(doc, list) else []
    
    for i, item in enumerate(items):
        if not is_step(item):
            continue
        
        before = yaml.safe_dump(item, sort_keys=False)
        
        # Apply transforms in order
        normalize_loop(item)
        normalize_tool(item)
        normalize_next(item)
        enforce_top_keys(item)
        
        after = yaml.safe_dump(item, sort_keys=False)
        changed |= (before != after)
    
    return doc, changed

def main(paths):
    """Process all provided YAML files"""
    for p in map(pathlib.Path, paths):
        if not p.exists():
            print(f"SKIP    {p} (not found)")
            continue
        
        try:
            txt = p.read_text()
            data = yaml.safe_load(txt)
            
            # Check if data is workflow section
            if isinstance(data, dict) and "workflow" in data:
                data["workflow"], changed = transform(data["workflow"])
            else:
                data, changed = transform(data)
            
            if changed:
                p.write_text(yaml.safe_dump(data, sort_keys=False, 
                                           default_flow_style=False))
                print(f"UPDATED {p}")
            else:
                print(f"OK      {p}")
        except Exception as e:
            print(f"ERROR   {p}: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python codemod_dsl_v2.py <path1> <path2> ...")
        sys.exit(1)
    main(sys.argv[1:])
```

**Notes:**
- This is a starter implementation
- Repository will need plugin-specific spec inference
- Better sink normalization required
- Keep in Git and iterate
- Always test on a copy first

---

## F. Regex Quick-Fixes (Optional, Pre-AST)

**⚠️ Use with care; prefer the Python codemod above.**

These are simple text-based replacements for quick fixes:

```bash
# ERROR: tool: iterator (manual conversion required)
\btool:\s*iterator\b → ERROR (manual: create loop block, remove)

# Convert aliases to loop
\b(iter|iterator|over|coll):\s*\n → loop:\n

# Move save (AST safer, but regex possible)
\n\s+sink:\s*\n → move under tool.result.sink

# Convert scalar next
\n\s+next:\s*([A-Za-z0-9_-]+)\s*$ → \n  next:\n    - step: \1
```

**Recommendation:** Only use for quick spot-checks, not bulk migration.

---

## G. Before/After Examples

### Example 1: Iterator-with-Task (Old) → Loop+Tool (New)

**Before:**
```yaml
- step: process_users
  tool: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: sequential
  task:
    task: process_users
    tool: playbook
    path: tests/.../user_profile_scorer
    return_step: finalize_result
    args:
      user_data: "{{ user }}"
    sink:
      tool: postgres
      table: public.user_profile_results
      key: id
      args:
        id: "{{ execution_id }}:{{ user.name }}"
```

**After:**
```yaml
- step: process_users
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: sequential
  tool:
    kind: playbook
    spec:
      path: tests/.../user_profile_scorer
      return_step: finalize_result
    args:
      user_data: "{{ user }}"
    result:
      sink:
        - postgres:
            table: public.user_profile_results
            key: id
            args:
              id: "{{ execution_id }}:{{ user.name }}"
```

**Changes:**
- `tool: iterator` removed
- `loop` block created with iteration config
- Nested `task` flattened into `tool`
- `save` converted to `result.sink` list

---

### Example 2: Step-Level Args/Save (Old) → Tool.Args/Result.Sink (New)

**Before:**
```yaml
- step: load_users
  tool: postgres
  args:
    query: "SELECT * FROM users"
  sink:
    tool: duckdb
    file: ./users.duckdb
    table: users
```

**After:**
```yaml
- step: load_users
  tool:
    kind: postgres
    spec: {}
    args:
      query: "SELECT * FROM users"
    result:
      sink:
        - duckdb:
            file: ./users.duckdb
            table: users
```

**Changes:**
- Scalar `tool: postgres` wrapped in structure
- `args` moved under `tool`
- `save` converted to `result.sink` list
- Sink keyed by type (`duckdb`)
- Redundant `storage` field removed

---

### Example 3: HTTP with Step-Level Config (Old) → Tool.Spec (New)

**Before:**
```yaml
- step: fetch_user
  tool: http
  method: GET
  endpoint: "{{ api }}/users/{{ user_id }}"
  headers:
    Authorization: "Bearer {{ token }}"
  params:
    limit: 10
```

**After:**
```yaml
- step: fetch_user
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "{{ api }}/users/{{ user_id }}"
      headers:
        Authorization: "Bearer {{ token }}"
      params:
        limit: 10
```

**Changes:**
- All HTTP config moved under `tool.spec`
- Step-level only contains 4-char keys

---

### Example 4: Multiple Sinks (Old) → Result.Sink List (New)

**Before:**
```yaml
- step: process_data
  tool: python
  code: |
    def main(input_data):
        return {"result": input_data * 2}
  sink:
    - tool: postgres
      table: results
      key: id
    - storage: s3
      bucket: data-lake
      key: "results/{{ execution_id }}.json"
```

**After:**
```yaml
- step: process_data
  tool:
    kind: python
    spec:
      code: |
        def main(input_data):
            return {"result": input_data * 2}
    result:
      sink:
        - postgres:
            table: results
            key: id
        - s3:
            bucket: data-lake
            key: "results/{{ execution_id }}.json"
```

**Changes:**
- `save` list converted to `result.sink`
- Each sink keyed by type
- `storage` field removed (redundant)

---

## H. Edge Cases & Decisions

### 1. Multiple Sinks

**Rule:** Ensure list format; each item must be single-key map

```yaml
# ✓ Valid
result:
  sink:
    - postgres: { table: users }
    - s3: { bucket: data }

# ✗ Invalid
result:
  sink:
    postgres: { table: users }  # ERROR: not a list
```

---

### 2. Unknown Top-Level Keys

**Strategy:**
1. Try to migrate into `tool.spec`
2. If not plugin-specific, leave and log **WARN**
3. Schema validation will fail later if truly invalid

**Example:**
```yaml
step: foo
custom_key: value      # Unknown key

# After codemod: leaves custom_key (logs warning)
# Schema validation: fails (blocks deployment)
```

---

### 3. Scalar `next` with Guards

**Rule:** Convert to list; preserve order; ensure only last item can omit `when`

```yaml
# Before (invalid - scalar with guard elsewhere)
next: default_step
when: "{{ condition }}"     # Wrong level!

# After (fixed in validation, not codemod)
next:
  - when: "{{ condition }}"
    step: default_step
```

---

### 4. Playbook/Workbook as Tools

**Enforce:** `kind: playbook|workbook` + `spec.path|spec.name`

```yaml
# ✓ Valid
tool:
  kind: playbook
  spec:
    path: playbooks/scorer

# ✗ Invalid
tool: playbook           # Missing spec
path: playbooks/scorer   # Wrong level
```

---

### 5. Reserved Namespace

**Rule:** Authors cannot write `bind.step` or `result.as: step`

**Validator must reject:**
```yaml
# ✗ ERROR: Cannot bind to reserved 'step'
bind:
  step: value

# ✗ ERROR: Cannot store result as 'step'
tool:
  result:
    as: step
```

**Reason:** `step` namespace is reserved for engine status (`step.<id>.status.*`)

---

## I. VS Code Automation (Tasks + How to Run)

### .vscode/tasks.json

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "dsl:lint",
      "type": "shell",
      "command": "python scripts/dsl_lint.py fixtures/**/*.yaml examples/**/*.yaml",
      "problemMatcher": []
    },
    {
      "label": "dsl:codemod",
      "type": "shell",
      "command": "python scripts/codemod_dsl_v2.py fixtures/**/*.yaml examples/**/*.yaml",
      "problemMatcher": []
    },
    {
      "label": "dsl:validate",
      "type": "shell",
      "command": "python scripts/validate_dsl_v2.py fixtures/**/*.yaml examples/**/*.yaml",
      "problemMatcher": []
    },
    {
      "label": "dsl:fix+validate",
      "dependsOn": ["dsl:codemod", "dsl:validate"],
      "problemMatcher": []
    },
    {
      "label": "dsl:test",
      "type": "shell",
      "command": "pytest -q tests/",
      "dependsOn": ["dsl:fix+validate"],
      "problemMatcher": []
    }
  ]
}
```

---

### Run Sequence

**In VS Code terminal or task runner:**

1. **Lint:** `Tasks: Run Task → dsl:lint`
   - Detect violations
   - Generate report
   - No file changes

2. **Codemod:** `Tasks: Run Task → dsl:codemod`
   - Apply transformations
   - Modify files
   - Idempotent (safe to re-run)

3. **Validate:** `Tasks: Run Task → dsl:validate`
   - Schema validation
   - Custom lints
   - Block on errors

4. **Fix+Validate:** `Tasks: Run Task → dsl:fix+validate`
   - Combined: codemod + validate
   - One-click migration

5. **Test:** `Tasks: Run Task → dsl:test` or `pytest -q`
   - Run unit tests
   - Run e2e tests
   - Verify no regressions

---

## J. Commit Plan & PR Checklist

### Branch Strategy

**Branch:** `refactor/dsl-v2-surface`

---

### Commit Sequence

**Commit 1:** Add tooling (no file changes)
```bash
git add scripts/codemod_dsl_v2.py
git add scripts/dsl_lint.py
git add scripts/validate_dsl_v2.py
git commit -m "feat: add DSL v2 migration tooling (lint, codemod, validate)"
```

**Commit 2:** Apply mechanical changes
```bash
python scripts/codemod_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml
git add examples/ tests/fixtures/
git commit -m "refactor: apply DSL v2 codemods (mechanical transforms)"
```

**Commit 3:** Semantic tweaks
```bash
# Manual edits: add result.as, optional collect.into
git add examples/ tests/fixtures/
git commit -m "refactor: add DSL v2 semantic enhancements (as, collect)"
```

**Commit 4:** Update documentation
```bash
git add docs/ README.md CHANGELOG.md
git commit -m "docs: update for DSL v2 surface"
```

---

### CI Configuration

Add legacy test to CI pipeline:

```yaml
# .github/workflows/ci.yml
- name: Validate DSL v2 Compliance
  run: |
    python scripts/validate_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml
    
- name: Lint for Legacy Constructs
  run: |
    ! grep -r "tool: iterator" examples/ tests/fixtures/
    ! grep -r "^  args:" examples/ tests/fixtures/ | grep -v "tool:"
    ! grep -r "^  sink:" examples/ tests/fixtures/ | grep -v "result:"
    ! grep -r "^  task:" examples/ tests/fixtures/
```

---

### PR Checklist

**Before merging, verify:**

- [ ] **No `tool: iterator`** anywhere
- [ ] **All steps** exclusively use `{step,desc,when,bind,loop,tool,next}`
- [ ] **All plugin configs** live at `tool.spec`
- [ ] **All persistence** at `tool.result.sink` (list format)
- [ ] **All `next` entries** are objects `{step, when?}`
- [ ] **All previous examples** pass `validate_dsl_v2.py`
- [ ] **All tests pass** (unit + e2e)
- [ ] **Documentation updated** (README, guides, samples)
- [ ] **CHANGELOG updated** with migration notes

---

## K. Rollback Plan

### Pre-Migration Tag

```bash
git tag pre-dsl-v2
git push origin pre-dsl-v2
```

---

### Rollback Options

**Option 1: Git revert**
```bash
# Revert to pre-migration state
git reset --hard pre-dsl-v2
```

**Option 2: Selective rollback** (if needed)
```bash
# Codemods are deterministic; re-run on clean tree
git checkout HEAD -- examples/ tests/fixtures/
python scripts/codemod_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml
```

**Option 3: Reverse codemod** (optional)

Create `scripts/codemod_dsl_v2_reverse.py` to re-expand `tool` to step-level fields:

```python
def reverse_transform(step):
    """Reverse DSL v2 transforms (for selective rollback)"""
    if "tool" in step and isinstance(step["tool"], dict):
        tool = step["tool"]
        
        # Extract args to step level
        if "args" in tool:
            step["args"] = tool.pop("args")
        
        # Extract result.sink to step-level save
        if "result" in tool and "sink" in tool["result"]:
            sinks = tool["result"]["sink"]
            if len(sinks) == 1:
                step["save"] = list(sinks[0].values())[0]
            else:
                step["save"] = sinks
        
        # Simplify scalar tool
        if tool == {"kind": kind, "spec": {}}:
            step["tool"] = kind
```

---

## L. Post-Migration "Gotchas"

### 1. Context Name Conflicts

**Issue:** Adopting `result.as` may shadow existing context variables

**Solution:** Choose unique `as` names
```yaml
# ✓ Good: explicit unique names
result:
  as: user_raw        # Not just 'user'
  
result:
  as: user_score      # Not just 'score'
```

---

### 2. Edge "Else" Semantics

**Issue:** Final `next` entry without `when` acts as else-fallthrough

**Solution:** Ensure final entry has no `when` if you intend else behavior
```yaml
next:
  - when: "{{ score > 80 }}"
    step: high
  - when: "{{ score > 50 }}"
    step: medium
  - step: low            # ✓ Else (no when)
```

---

### 3. Parallel Loop Idempotency

**Issue:** If sinks aren't idempotent, parallel execution may cause issues

**Solution:**
- Set `mode: sequential` for non-idempotent sinks
- Add uniqueness constraints (key) carefully
- Use proper upsert modes

```yaml
loop:
  mode: sequential     # ✓ Safe for non-idempotent sinks
  
result:
  sink:
    - postgres:
        mode: upsert   # ✓ Idempotent
        key: id
```

---

### 4. Validation Strictness

**Issue:** Enforce 4-char step keys now; legacy aliases only in transitional parser mode

**Solution:**
- Enable strict validation in production
- Allow legacy mode only during migration period
- Set deprecation timeline for legacy support

```python
# Validator configuration
STRICT_MODE = True  # Enforce 4-char keys
ALLOW_LEGACY = False  # Disable after migration
```

---

## Next Steps

This document defines the **migration strategy and codemods**. Next portions will cover:

1. **Schema & Validation**: JSON Schema for new DSL, validation rules, error messages
2. **Engine Implementation**: Core engine changes to support new DSL features
3. **Testing Strategy**: Unit tests, e2e tests, migration verification

---

**Ready for next portion of the refactoring plan.**
