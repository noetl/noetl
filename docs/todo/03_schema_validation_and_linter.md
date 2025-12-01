# JSON Schema, EBNF, and Validator/Linter Implementation

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Define formal schema, grammar, and validation tooling for DSL v2

---

## 3.1 JSON Schema (Draft 2020-12)

**Scope:** Workflow steps list (array of step objects). Enforces 4-char top keys, loop/tool/next semantics, result.sink as list of single-key objects, and edge/step when usage.

**File:** `scripts/workflow-steps.v2.json`

```json
{
  "$id": "https://noetl.dev/schema/workflow-steps.v2.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "NoETL Workflow Steps (v2)",
  "type": "array",
  "minItems": 1,
  "items": {
    "$ref": "#/$defs/step"
  },
  "$defs": {
    "jinjaExpr": {
      "type": "string",
      "minLength": 1
    },
    "stepId": {
      "type": "string",
      "minLength": 1,
      "pattern": "^[A-Za-z0-9_\\-\\.]+$"
    },
    "sinkItem": {
      "type": "object",
      "minProperties": 1,
      "maxProperties": 1,
      "additionalProperties": {
        "type": "object"
      }
    },
    "result": {
      "type": "object",
      "properties": {
        "as": { "type": "string", "minLength": 1 },
        "pick": { "$ref": "#/$defs/jinjaExpr" },
        "sink": {
          "type": "array",
          "items": { "$ref": "#/$defs/sinkItem" }
        },
        "collect": {
          "type": "object",
          "properties": {
            "into": { "type": "string", "minLength": 1 },
            "mode": { "type": "string", "enum": ["list", "map"] },
            "key": { "$ref": "#/$defs/jinjaExpr" }
          },
          "required": ["into"],
          "allOf": [
            {
              "if": { "properties": { "mode": { "const": "map" } } },
              "then": { "required": ["key"] }
            }
          ],
          "additionalProperties": false
        }
      },
      "additionalProperties": false
    },
    "loop": {
      "type": "object",
      "properties": {
        "collection": { "$ref": "#/$defs/jinjaExpr" },
        "element":    { "type": "string", "minLength": 1 },
        "mode":       { "type": "string", "enum": ["sequential", "parallel"] },
        "until":      { "$ref": "#/$defs/jinjaExpr" }
      },
      "required": ["collection", "element"],
      "additionalProperties": false
    },
    "tool": {
      "type": "object",
      "properties": {
        "kind": { "type": "string", "minLength": 1 },
        "spec": { "type": "object" },
        "args": { "type": "object" },
        "result": { "$ref": "#/$defs/result" }
      },
      "required": ["kind", "spec"],
      "additionalProperties": false,
      "allOf": [
        {
          "if": { "properties": { "kind": { "const": "playbook" } } },
          "then": {
            "properties": {
              "spec": {
                "type": "object",
                "properties": {
                  "path": { "type": "string", "minLength": 1 },
                  "entry_step": { "$ref": "#/$defs/stepId" },
                  "return_step": { "$ref": "#/$defs/stepId" }
                },
                "required": ["path"],
                "additionalProperties": false
              }
            }
          }
        },
        {
          "if": { "properties": { "kind": { "const": "workbook" } } },
          "then": {
            "properties": {
              "spec": {
                "type": "object",
                "properties": {
                  "name": { "type": "string", "minLength": 1 }
                },
                "required": ["name"],
                "additionalProperties": false
              }
            }
          }
        },
        {
          "if": { "properties": { "kind": { "const": "http" } } },
          "then": {
            "properties": {
              "spec": {
                "type": "object",
                "properties": {
                  "method":   { "type": "string", "minLength": 1 },
                  "endpoint": { "$ref": "#/$defs/jinjaExpr" },
                  "headers":  { "type": "object" },
                  "params":   { "type": "object" },
                  "payload":  {}
                },
                "required": ["method", "endpoint"],
                "additionalProperties": true
              }
            }
          }
        },
        {
          "if": { "properties": { "kind": { "const": "postgres" } } },
          "then": {
            "properties": {
              "spec": {
                "type": "object",
                "properties": {
                  "query": { "type": "string", "minLength": 1 },
                  "auth":  {},
                  "params": { "type": "object" }
                },
                "required": ["query"],
                "additionalProperties": true
              }
            }
          }
        },
        {
          "if": { "properties": { "kind": { "const": "python" } } },
          "then": {
            "properties": {
              "spec": {
                "type": "object",
                "properties": {
                  "code": { "type": "string", "minLength": 1 },
                  "module": { "type": "string" },
                  "callable": { "type": "string" }
                },
                "oneOf": [
                  { "required": ["code"] },
                  { "required": ["module", "callable"] }
                ],
                "additionalProperties": false
              }
            }
          }
        },
        {
          "if": { "properties": { "kind": { "const": "duckdb" } } },
          "then": {
            "properties": {
              "spec": {
                "type": "object",
                "properties": {
                  "query": { "type": "string", "minLength": 1 },
                  "file":  { "type": "string" }
                },
                "required": ["query"],
                "additionalProperties": true
              }
            }
          }
        }
      ]
    },
    "nextEdge": {
      "type": "object",
      "properties": {
        "step": { "$ref": "#/$defs/stepId" },
        "when": { "$ref": "#/$defs/jinjaExpr" }
      },
      "required": ["step"],
      "additionalProperties": false
    },
    "step": {
      "type": "object",
      "properties": {
        "step": { "$ref": "#/$defs/stepId" },
        "desc": { "type": "string" },
        "when": { "$ref": "#/$defs/jinjaExpr" },
        "bind": { "type": "object" },
        "loop": { "$ref": "#/$defs/loop" },
        "tool": { "$ref": "#/$defs/tool" },
        "next": {
          "type": "array",
          "items": { "$ref": "#/$defs/nextEdge" },
          "minItems": 1
        }
      },
      "required": ["step"],
      "allOf": [
        {
          "if": { "not": { "properties": { "tool": {} } } },
          "then": { "properties": { "next": { "minItems": 1 } } }
        }
      ],
      "additionalProperties": false
    }
  }
}
```

---

### Schema Notes

**Key Enforcement Mechanisms:**

1. **4-char top-level keys:** `additionalProperties: false` in `step` definition ensures only `{step, desc, when, bind, loop, tool, next}` are allowed

2. **Plugin-specific specs:** `tool.kind` controls the shape of `tool.spec` via conditional schemas (`if/then`)

3. **Single-key sinks:** `result.sink` is a list where each item must be an object with exactly one key (enforced by `minProperties: 1, maxProperties: 1`)

4. **Mode-dependent collect:** If `collect.mode` is `"map"`, then `collect.key` is required (enforced by `allOf`)

5. **Step without tool:** If step has no `tool`, it must have `next` (routing-only step)

**Schema Limitations:**

The schema **cannot** express:
- "At most one `next` item without `when`" (checked in linter)
- Forbidden writes to `step.*` namespace via `bind` or `result.as` (checked in linter)
- Reachability analysis (checked in linter)
- Jinja expression validity (checked at runtime)

---

## 3.2 EBNF (ISO/IEC 14977-Style)

**Purpose:** Formal grammar for documentation; mirrors Portion 1 semantics.

```ebnf
workflow      = { step_def } ;

step_def      = "- step:" step_id , NL , { step_attr } ;

step_attr     = desc | when | bind | loop | tool | next ;

desc          = "desc:" , text ;
when          = "when:" , jinja_expr ;
bind          = "bind:" , map ;

loop          = "loop:" , map_loop ;
map_loop      = "{" , "collection:" , jinja_expr , "," ,
                     "element:" , ident , [ "," , "mode:" , ("sequential"|"parallel") ] ,
                     [ "," , "until:" , jinja_expr ] , "}" ;

tool          = "tool:" , map_tool ;
map_tool      = "{" ,
                  "kind:" , ident , "," ,
                  "spec:" , map , [ "," ,
                  "args:" , map ] , [ "," ,
                  "result:" , map_result ] , "}" ;

map_result    = "{" ,
                  [ "as:" , ident , "," ] ,
                  [ "pick:" , jinja_expr , "," ] ,
                  [ "collect:" , map_collect , "," ] ,
                  "sink:" , list_sink ,
                "}" ;

map_collect   = "{" , "into:" , ident ,
                  [ "," , "mode:" , ("list"|"map") ] ,
                  [ "," , "key:" , jinja_expr ] , "}" ;

list_sink     = "[" , { one_sink , [ "," ] } , "]" ;
one_sink      = "{" , sink_id , ":" , map , "}" ;

next          = "next:" , "[" , next_edge , { "," , next_edge } , "]" ;
next_edge     = "{" , [ "when:" , jinja_expr , "," ] , "step:" , step_id , "}" ;

(* Lexical *)
step_id       = ident ;
sink_id       = ident ;
ident         = letter , { letter | digit | "_" | "-" | "." } ;
jinja_expr    = text ;   (* must be valid Jinja at runtime *)
text          = (* YAML string *) ;
map           = (* YAML mapping *) ;
NL            = (* newline(s) *) ;
```

---

## 3.3 Python Validator + Linter Implementation

### 3.3.1 Schema Validator

**File:** `scripts/validate_dsl_v2.py`

```python
#!/usr/bin/env python3
"""
DSL v2 JSON Schema Validator

Validates NoETL workflow YAML files against the workflow-steps.v2.json schema.
Enforces structural correctness: 4-char keys, tool/loop/next formats, etc.

Usage:
    python scripts/validate_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml
"""
import sys, json, yaml, pathlib
from jsonschema import Draft202012Validator

SCHEMA_PATH = pathlib.Path(__file__).parent / "workflow-steps.v2.json"

def load_yaml(p):
    """Load YAML file safely"""
    with open(p, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def main(paths):
    """Validate all provided YAML files against schema"""
    schema = json.loads(SCHEMA_PATH.read_text())
    validator = Draft202012Validator(schema)
    ok = True
    
    for raw in paths:
        p = pathlib.Path(raw)
        if not p.exists(): 
            print(f"ERR  missing: {p}")
            ok = False
            continue
        
        data = load_yaml(p)
        
        # Accept either a top-level mapping with 'workflow' or a raw list of steps
        steps = data.get("workflow") if isinstance(data, dict) and "workflow" in data else data
        
        if not isinstance(steps, list):
            print(f"ERR  {p}: top-level must be a list of steps or contain 'workflow' as a list")
            ok = False
            continue
        
        errors = sorted(validator.iter_errors(steps), key=lambda e: e.path)
        
        if errors:
            ok = False
            print(f"FAIL {p}: {len(errors)} schema errors")
            for e in errors:
                path = "/".join([str(x) for x in e.path])
                print(f"  - at {path or '<root>'}: {e.message}")
        else:
            print(f"OK   {p}")
    
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python validate_dsl_v2.py <path1> <path2> ...")
        sys.exit(1)
    main(sys.argv[1:])
```

---

### 3.3.2 Semantic Linter

**File:** `scripts/lint_dsl_v2.py`

```python
#!/usr/bin/env python3
"""
DSL v2 Semantic Linter

Checks semantic constraints that JSON Schema cannot express:
- At most one next edge without 'when' (else)
- No reserved namespace violations (bind.step, result.as: step)
- No legacy constructs (tool: iterator, iter/iterator/over/coll aliases)
- Proper sink structure (single-key maps)

Usage:
    python scripts/lint_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml
"""
import sys, yaml, pathlib

ALLOWED_TOP = {"step", "desc", "when", "bind", "loop", "tool", "next"}  # 4-char keys

def load_steps(p):
    """Load workflow steps from YAML file"""
    data = yaml.safe_load(p.read_text())
    return data.get("workflow") if isinstance(data, dict) and "workflow" in data else data

def lint_single_key_sink(sinks):
    """Ensure result.sink is a list of single-key objects"""
    errs = []
    if not isinstance(sinks, list): 
        errs.append("result.sink must be a list")
        return errs
    
    for i, item in enumerate(sinks):
        if not isinstance(item, dict):
            errs.append(f"result.sink[{i}] must be an object with exactly one key")
        else:
            if len(item.keys()) != 1:
                errs.append(f"result.sink[{i}] must have exactly one key (sink id)")
    return errs

def lint_next_edges(nx):
    """Ensure next is array of {step, when?} with at most one else"""
    errs = []
    if not isinstance(nx, list): 
        errs.append("next must be a list")
        return errs
    
    else_count = 0
    for i, ed in enumerate(nx):
        if not isinstance(ed, dict) or "step" not in ed:
            errs.append(f"next[{i}] must be an object with 'step'")
            continue
        if "when" not in ed:
            else_count += 1
    
    if else_count > 1:
        errs.append("next may contain at most one edge without 'when' (else)")
    
    return errs

def lint_reserved_namespace(step_obj):
    """Disallow author writes to reserved 'step' namespace"""
    errs = []
    
    # Disallow author writing 'step' via bind
    if "bind" in step_obj and isinstance(step_obj["bind"], dict):
        if "step" in step_obj["bind"]:
            errs.append("bind.step is reserved and cannot be set by authors")
    
    # Disallow result.as: step
    tool = step_obj.get("tool")
    if isinstance(tool, dict):
        res = tool.get("result")
        if isinstance(res, dict) and res.get("as") == "step":
            errs.append("tool.result.as cannot be 'step' (reserved)")
    
    return errs

def lint_top_keys(step_obj):
    """Enforce only 4-char canonical keys at top level"""
    errs = []
    extra = [k for k in step_obj.keys() if k not in ALLOWED_TOP]
    if extra:
        errs.append(f"top-level keys must be {sorted(ALLOWED_TOP)}; found extras: {extra}")
    return errs

def lint_loop_aliases(step_obj):
    """Detect legacy iteration constructs"""
    errs = []
    
    # Check for legacy aliases
    for alias in ("iter", "iterator", "over", "coll"):
        if alias in step_obj:
            errs.append(f"use 'loop' instead of '{alias}'")
    
    # Check for tool: iterator
    if "tool" in step_obj and step_obj.get("tool") == "iterator":
        errs.append("tool: iterator is invalid; use step.loop")
    
    return errs

def lint_file(steps, fname):
    """Run all lints on a file's workflow steps"""
    errs = []
    
    if not isinstance(steps, list):
        return [f"{fname}: expected list of steps"]
    
    # Step ids for reachability analysis (future enhancement)
    for idx, st in enumerate(steps):
        if not isinstance(st, dict) or "step" not in st:
            errs.append(f"{fname} step[{idx}]: must be an object with 'step'")
            continue
        
        step_id = st.get("step")
        
        # Run all lints
        errs += [f"{fname} {step_id}: {m}" for m in lint_top_keys(st)]
        errs += [f"{fname} {step_id}: {m}" for m in lint_loop_aliases(st)]
        errs += [f"{fname} {step_id}: {m}" for m in lint_reserved_namespace(st)]
        
        # Next edges
        if "next" in st:
            errs += [f"{fname} {step_id}: {m}" for m in lint_next_edges(st["next"])]
        
        # Sink single-key check
        tool = st.get("tool")
        if isinstance(tool, dict):
            res = tool.get("result", {})
            if "sink" in res:
                errs += [f"{fname} {step_id}: {m}" for m in lint_single_key_sink(res["sink"])]
    
    return errs

def main(paths):
    """Lint all provided YAML files"""
    ok = True
    
    for raw in paths:
        p = pathlib.Path(raw)
        if not p.exists():
            print(f"ERR  missing: {p}")
            ok = False
            continue
        
        steps = load_steps(p)
        errs = lint_file(steps, str(p))
        
        if errs:
            ok = False
            print(f"FAIL {p}: {len(errs)} lint errors")
            for e in errs:
                print("  -", e)
        else:
            print(f"OK   {p}")
    
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python lint_dsl_v2.py <path1> <path2> ...")
        sys.exit(1)
    main(sys.argv[1:])
```

---

## 3.4 Helper Injection (Jinja)

**Purpose:** Register engine status helpers so authors can write `{{ done('A') and ok('B') }}` in `when` conditions.

**File:** `scripts/jinja_helpers.py`

```python
"""
Jinja2 Engine Status Helpers

Provides step status query functions for use in when/next conditions:
- done(step_id): Step completed
- ok(step_id): Step succeeded
- fail(step_id): Step failed
- running(step_id): Step is running
- loop_done(step_id): Loop fully drained
- all_done([ids]): All steps done
- any_done([ids]): Any step done

Usage in DSL:
    when: "{{ done('extract_data') and ok('transform_data') }}"
    when: "{{ all_done(['step_a', 'step_b', 'step_c']) }}"
"""

def install_helpers(env, context_accessor):
    """
    Register step status helpers into Jinja2 environment.
    
    Args:
        env: jinja2.Environment instance
        context_accessor: callable returning the current evaluation context dict
                         (must return dict with step.<id>.status.* structure)
    
    Example:
        from jinja2 import Environment
        env = Environment()
        
        def get_context():
            return current_execution_context
        
        install_helpers(env, get_context)
    """
    def _st(sid):
        """Get step status dict for given step id"""
        ctx = context_accessor()
        return ctx.get("step", {}).get(sid, {}).get("status", {})
    
    # Register global functions
    env.globals.update({
        "done": lambda sid: bool(_st(sid).get("done")),
        
        "ok": lambda sid: bool(_st(sid).get("ok")),
        
        "fail": lambda sid: _st(sid).get("ok") is False,
        
        "running": lambda sid: bool(_st(sid).get("running")),
        
        "loop_done": lambda sid: bool(
            _st(sid).get("done") or (
                _st(sid).get("total") is not None 
                and _st(sid).get("completed") is not None 
                and _st(sid).get("completed") >= _st(sid).get("total")
            )
        ),
        
        "all_done": lambda sids: all(bool(_st(s).get("done")) for s in sids),
        
        "any_done": lambda sids: any(bool(_st(s).get("done")) for s in sids),
    })
```

---

### Helper Integration

**Wire this where you evaluate `when` / `next[].when`:**

```python
# Example: In noetl/core/dsl/render.py or execution engine

from jinja2 import Environment
from scripts.jinja_helpers import install_helpers

def create_dsl_environment(execution_context):
    """Create Jinja2 environment with DSL helpers"""
    env = Environment()
    
    # Context accessor closure
    def get_context():
        return execution_context
    
    # Install step status helpers
    install_helpers(env, get_context)
    
    return env

# Usage in step evaluation
env = create_dsl_environment(current_context)
template = env.from_string("{{ done('extract') and ok('transform') }}")
result = template.render(workload=workload_data)
```

---

## 3.5 VS Code Tasks (Validate + Lint)

**Add to `.vscode/tasks.json`** (augments Portion 2 tasks):

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "dsl:lint",
      "type": "shell",
      "command": "python scripts/lint_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml",
      "problemMatcher": []
    },
    {
      "label": "dsl:validate",
      "type": "shell",
      "command": "python scripts/validate_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml",
      "problemMatcher": []
    },
    {
      "label": "dsl:validate+lint",
      "type": "shell",
      "command": "python scripts/validate_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml && python scripts/lint_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml",
      "problemMatcher": []
    },
    {
      "label": "dsl:codemod",
      "type": "shell",
      "command": "python scripts/codemod_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml",
      "problemMatcher": []
    },
    {
      "label": "dsl:full-migration",
      "dependsOn": ["dsl:codemod", "dsl:validate+lint"],
      "problemMatcher": []
    }
  ]
}
```

---

### Task Usage

**Run sequence:**

1. **Lint only:** `Tasks: Run Task → dsl:lint`
   - Checks semantic constraints
   - No file modifications

2. **Validate only:** `Tasks: Run Task → dsl:validate`
   - Checks JSON Schema compliance
   - No file modifications

3. **Combined check:** `Tasks: Run Task → dsl:validate+lint`
   - Both schema and semantic checks
   - Fastest way to verify compliance

4. **Full migration:** `Tasks: Run Task → dsl:full-migration`
   - Runs codemod → validate → lint
   - Complete automated migration

---

## 3.6 Acceptance Criteria (Schema/Lint)

### Schema Validation (validate_dsl_v2.py)

**Pass criteria:**

- [ ] All workflow YAMLs validate against `workflow-steps.v2.json`
- [ ] No step contains keys outside `{step, desc, when, bind, loop, tool, next}`
- [ ] `tool.kind` + per-kind `tool.spec` required and correct
- [ ] `tool.result.sink` is a list of single-key objects only
- [ ] `next` is a list of `{ step, when? }` objects
- [ ] `loop` has required fields: `collection`, `element`
- [ ] `collect.mode: map` requires `collect.key`

---

### Semantic Linting (lint_dsl_v2.py)

**Pass criteria:**

- [ ] No `tool: iterator` anywhere
- [ ] No step-level `args` or `save`
- [ ] No nested `task:` blobs
- [ ] No legacy aliases: `iter`, `iterator`, `over`, `coll`
- [ ] At most one `next` edge without `when` (else)
- [ ] No reserved namespace violations:
  - `bind.step` not allowed
  - `result.as: step` not allowed
- [ ] All `result.sink` items are single-key maps

---

### Example Validation Output

**Valid file:**
```
OK   examples/user_scorer.yaml
OK   tests/fixtures/control_flow_workbook.yaml
```

**Invalid file:**
```
FAIL examples/legacy_iterator.yaml: 3 schema errors
  - at 0/tool: 'iterator' is not valid under any of the given schemas
  - at 0/args: Additional properties are not allowed ('args' was unexpected)
  - at 0/sink: Additional properties are not allowed ('save' was unexpected)

FAIL examples/legacy_iterator.yaml: 5 lint errors
  - examples/legacy_iterator.yaml process_users: tool: iterator is invalid; use step.loop
  - examples/legacy_iterator.yaml process_users: top-level keys must be ['bind', 'desc', 'loop', 'next', 'step', 'tool', 'when']; found extras: ['args', 'save']
  - examples/legacy_iterator.yaml process_users: use 'loop' instead of 'iterator'
```

---

## 3.7 Integration with Existing Codebase

### 3.7.1 Add Schema File

```bash
# Create schema file
mkdir -p scripts/
cat > scripts/workflow-steps.v2.json << 'EOF'
{
  "$id": "https://noetl.dev/schema/workflow-steps.v2.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  ...
}
EOF
```

---

### 3.7.2 Add Validator/Linter Scripts

```bash
# Create validator
cat > scripts/validate_dsl_v2.py << 'EOF'
#!/usr/bin/env python3
...
EOF
chmod +x scripts/validate_dsl_v2.py

# Create linter
cat > scripts/lint_dsl_v2.py << 'EOF'
#!/usr/bin/env python3
...
EOF
chmod +x scripts/lint_dsl_v2.py

# Create Jinja helpers
cat > scripts/jinja_helpers.py << 'EOF'
...
EOF
```

---

### 3.7.3 Install Dependencies

```bash
# Add to pyproject.toml or requirements.txt
pip install jsonschema pyyaml
```

---

### 3.7.4 Update CI Pipeline

```yaml
# .github/workflows/ci.yml or similar
- name: Validate DSL v2 Schema
  run: python scripts/validate_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml

- name: Lint DSL v2 Semantics
  run: python scripts/lint_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml
```

---

### 3.7.5 Wire Jinja Helpers into Engine

**Location:** `noetl/core/dsl/render.py` or similar

```python
from scripts.jinja_helpers import install_helpers

class DSLRenderer:
    def __init__(self, execution_context):
        self.context = execution_context
        self.env = Environment()
        install_helpers(self.env, lambda: self.context)
    
    def evaluate_when(self, when_expr):
        """Evaluate step when condition"""
        template = self.env.from_string(when_expr)
        return template.render(**self.context)
```

---

## 3.8 Error Message Examples

### Schema Validation Errors

```
FAIL examples/bad_tool.yaml: 2 schema errors
  - at 0/tool/spec: 'path' is a required property
  - at 0/tool: Additional properties are not allowed ('invalid_key' was unexpected)
```

---

### Lint Errors

```
FAIL examples/bad_next.yaml: 2 lint errors
  - examples/bad_next.yaml step_a: next may contain at most one edge without 'when' (else)
  - examples/bad_next.yaml step_b: result.sink[0] must have exactly one key (sink id)
```

---

### Reserved Namespace Violations

```
FAIL examples/bad_bind.yaml: 1 lint errors
  - examples/bad_bind.yaml load_data: bind.step is reserved and cannot be set by authors
```

---

## 3.9 Testing Strategy

### Unit Tests for Validator/Linter

**File:** `tests/test_dsl_v2_validation.py`

```python
import pytest
from scripts.validate_dsl_v2 import main as validate
from scripts.lint_dsl_v2 import main as lint

def test_valid_workflow_passes():
    """Valid DSL v2 workflow passes both schema and lint"""
    # Create valid YAML fixture
    # Run validator
    # Assert exit code 0

def test_legacy_iterator_fails():
    """Legacy tool: iterator fails lint"""
    # Create YAML with tool: iterator
    # Run lint
    # Assert exit code 1 and correct error message

def test_multiple_else_edges_fails():
    """Multiple next edges without when fails lint"""
    # Create YAML with 2+ edges without when
    # Run lint
    # Assert exit code 1

def test_reserved_namespace_fails():
    """Writing to step namespace fails lint"""
    # Create YAML with bind.step or result.as: step
    # Run lint
    # Assert exit code 1
```

---

## Next Steps

This document defines the **formal schema, grammar, and validation tooling**. Next portions will cover:

1. **Engine Implementation**: Core execution engine changes to support new DSL features
2. **Plugin Refactoring**: Adapter layer for plugins to consume new tool structure
3. **Testing Strategy**: Unit tests, integration tests, migration verification

---

**Ready for next portion of the refactoring plan.**
