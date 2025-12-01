# CLI/Makefile, PR Template, CI, Migration Cookbook

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Provide automation, CI integration, PR templates, and migration recipes for DSL v2 adoption

---

## 5.1 Makefile Targets (One-Liners You Can Chain)

**File:** `Makefile` (add to existing or create new)

```makefile
## ===== DSL v2: validation & codemods =====
PY := python

DSL_FIXTURES := tests/fixtures/workflows/v2/**/*.yaml examples/**/*.yaml
DSL_SCHEMA   := scripts/validate_dsl_v2.py
DSL_LINT     := scripts/lint_dsl_v2.py
DSL_CODEMOD  := scripts/codemod_dsl_v2.py

.PHONY: dsl.lint
dsl.lint:
	$(PY) $(DSL_LINT) $(DSL_FIXTURES)

.PHONY: dsl.validate
dsl.validate:
	$(PY) $(DSL_SCHEMA) $(DSL_FIXTURES)

.PHONY: dsl.codemod
dsl.codemod:
	$(PY) $(DSL_CODEMOD) $(DSL_FIXTURES)

.PHONY: dsl.fix+validate
dsl.fix+validate: dsl.codemod dsl.validate dsl.lint

## ===== Test shortcuts =====
.PHONY: test
test:
	pytest -q

.PHONY: dsl.all
dsl.all: dsl.codemod dsl.validate dsl.lint test
```

---

### Suggested Local Development Flow

```bash
# 1. Check current state (find violations)
make dsl.lint

# 2. Auto-fix with codemod (mechanical transforms)
make dsl.codemod

# 3. Validate schema compliance
make dsl.validate

# 4. Run full test suite
make test

# Or run everything at once
make dsl.all
```

---

### Individual Target Usage

```bash
# Lint only
make dsl.lint

# Schema validation only
make dsl.validate

# Apply codemods only
make dsl.codemod

# Fix + validate (codemod → validate → lint)
make dsl.fix+validate

# Full pipeline (codemod → validate → lint → test)
make dsl.all
```

---

## 5.2 CLI Commands (Human-Friendly Wrappers)

**File:** `cli/dsl.py`

```python
#!/usr/bin/env python3
"""
DSL v2 CLI

Human-friendly command-line interface for DSL validation, linting, and migration.

Usage:
    python cli/dsl.py lint [PATH...]
    python cli/dsl.py validate [PATH...]
    python cli/dsl.py codemod [PATH...]

Examples:
    python cli/dsl.py lint
    python cli/dsl.py validate tests/fixtures/workflows/v2/**/*.yaml
    python cli/dsl.py codemod examples/**/*.yaml
"""
import click
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
PY   = sys.executable

def run(*parts):
    """Run command and return exit code"""
    return subprocess.call([*parts])

@click.group()
def dsl():
    """DSL v2 validation and migration tools"""
    pass

@dsl.command("lint")
@click.argument("paths", nargs=-1)
def lint(paths):
    """
    Run semantic linter on workflow files.
    
    Checks for:
    - Legacy constructs (tool: iterator, step-level args/save)
    - Reserved namespace violations
    - Next edge constraints (at most one else)
    - Single-key sink structure
    
    If no paths provided, defaults to tests/fixtures/workflows/v2/
    """
    target = ROOT / "scripts" / "lint_dsl_v2.py"
    default_paths = [str(ROOT / "tests" / "fixtures" / "workflows" / "v2")]
    sys.exit(run(PY, str(target), *(paths or default_paths)))

@dsl.command("validate")
@click.argument("paths", nargs=-1)
def validate(paths):
    """
    Validate workflow files against JSON Schema.
    
    Checks structural correctness:
    - 4-char top-level keys
    - tool.kind + per-kind tool.spec
    - result.sink as list
    - next as list of edges
    
    If no paths provided, defaults to tests/fixtures/workflows/v2/
    """
    target = ROOT / "scripts" / "validate_dsl_v2.py"
    default_paths = [str(ROOT / "tests" / "fixtures" / "workflows" / "v2")]
    sys.exit(run(PY, str(target), *(paths or default_paths)))

@dsl.command("codemod")
@click.argument("paths", nargs=-1)
def codemod(paths):
    """
    Apply automated DSL v2 migrations.
    
    Transforms:
    - tool: iterator → loop block
    - Nested task: → tool structure
    - Step-level args/save → tool.args/result.sink
    - Scalar next → array of edges
    
    If no paths provided, defaults to examples/ and tests/fixtures/
    
    WARNING: Modifies files in place. Commit changes first!
    """
    target = ROOT / "scripts" / "codemod_dsl_v2.py"
    default_paths = [str(ROOT / "examples"), str(ROOT / "tests/fixtures")]
    sys.exit(run(PY, str(target), *(paths or default_paths)))

@dsl.command("all")
@click.argument("paths", nargs=-1)
def all_checks(paths):
    """
    Run full migration pipeline: codemod → validate → lint.
    
    Equivalent to:
        dsl codemod [paths]
        dsl validate [paths]
        dsl lint [paths]
    """
    click.echo("Running codemod...")
    ctx = click.get_current_context()
    ctx.invoke(codemod, paths=paths)
    
    click.echo("\nRunning validation...")
    ctx.invoke(validate, paths=paths)
    
    click.echo("\nRunning lint...")
    ctx.invoke(lint, paths=paths)
    
    click.echo("\n✓ All checks complete")

if __name__ == "__main__":
    dsl()
```

---

### CLI Usage Examples

```bash
# Lint with default paths
python cli/dsl.py lint

# Lint specific files
python cli/dsl.py lint examples/my_workflow.yaml tests/fixtures/test_*.yaml

# Validate all workflows
python cli/dsl.py validate tests/fixtures/workflows/v2/**/*.yaml

# Apply codemod to examples
python cli/dsl.py codemod examples/**/*.yaml

# Run full pipeline
python cli/dsl.py all

# Get help
python cli/dsl.py --help
python cli/dsl.py lint --help
```

---

## 5.3 GitHub PR Template & Checklist

**File:** `.github/pull_request_template.md`

```markdown
## Purpose
<!-- What this PR changes and why -->

---

## DSL v2 Checklist

### Structural Compliance
- [ ] No usage of `tool: iterator`
- [ ] No step-level `args` or `save` (moved to `tool.args` / `tool.result.sink`)
- [ ] No nested `task:` blobs (flattened into `tool`)
- [ ] Step keys are **exactly**: `step, desc, when, bind, loop, tool, next`
- [ ] `tool.kind` + per-kind `tool.spec` validated
- [ ] `tool.result.sink` is a **list** of single-key objects
- [ ] `next` is an ordered list; at most one edge without `when` (else)

### Semantic Compliance
- [ ] Guards use helpers where appropriate: `done('A')`, `ok('B')`, `loop_done('C')`
- [ ] Reserved namespace respected (no `bind.step`, no `result.as: step`)
- [ ] Loop structure uses `loop.collection`, `loop.element`, `loop.mode`
- [ ] Result handling follows pipeline: `tool → pick → as → collect → sink`

### Validation
- [ ] `make dsl.validate` passes (JSON Schema)
- [ ] `make dsl.lint` passes (semantic checks)
- [ ] `make test` passes (unit + integration tests)
- [ ] All examples/fixtures updated

---

## Changes Summary

### Files Modified
<!-- List modified workflow files -->

### Migration Approach
<!-- How did you migrate? Manual, codemod, hybrid? -->

### Manual Adjustments
<!-- Any manual tweaks after codemod? -->
- [ ] Added `result.as` for context storage
- [ ] Added `result.collect` for loop accumulation
- [ ] Refactored guards to use engine helpers
- [ ] Other: _______

---

## Testing

### Local Validation
```bash
# Commands run locally
make dsl.validate  # ✅ / ❌
make dsl.lint      # ✅ / ❌
make test          # ✅ / ❌
```

### Test Coverage
- [ ] Existing tests pass
- [ ] New tests added (if applicable)
- [ ] Golden fixtures updated
- [ ] Negative fixtures added for new patterns

---

## Notes
<!-- Migrations performed, known edge cases, follow-ups, rollback plan -->

### Known Issues
<!-- Any remaining violations or edge cases? -->

### Follow-Up Tasks
<!-- Issues to address in future PRs -->

### Rollback Plan
<!-- How to revert if needed -->
- Git tag: `pre-dsl-v2` (created before migration)
- Revert command: `git reset --hard pre-dsl-v2`

---

## Checklist for Reviewers
- [ ] All DSL v2 checklist items verified
- [ ] Validation commands run successfully
- [ ] No legacy constructs remain
- [ ] Guards use helpers appropriately
- [ ] Documentation updated if needed
```

---

## 5.4 CI Wiring (GitHub Actions)

**File:** `.github/workflows/dsl-v2.yml`

```yaml
name: DSL v2 Checks

on:
  pull_request:
    paths:
      - 'examples/**/*.yaml'
      - 'tests/fixtures/**/*.yaml'
      - 'scripts/validate_dsl_v2.py'
      - 'scripts/lint_dsl_v2.py'
      - 'scripts/workflow-steps.v2.json'
  push:
    branches:
      - main
      - master

jobs:
  dsl-validation:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Cache dependencies
        uses: actions/cache@v3
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install jsonschema pyyaml pytest click
      
      - name: Validate Schema
        run: make dsl.validate
      
      - name: Lint Semantics
        run: make dsl.lint
      
      - name: Run Tests
        run: make test
      
      - name: Check for legacy constructs
        run: |
          # Fail if any legacy patterns found
          ! grep -r "tool: iterator" examples/ tests/fixtures/ || (echo "ERROR: tool: iterator found" && exit 1)
          ! grep -r "^  args:" examples/ tests/fixtures/ | grep -v "tool:" || (echo "ERROR: step-level args found" && exit 1)
          ! grep -r "^  sink:" examples/ tests/fixtures/ | grep -v "result:" || (echo "ERROR: step-level save found" && exit 1)
          ! grep -r "^  task:" examples/ tests/fixtures/ || (echo "ERROR: nested task found" && exit 1)

  dsl-test-suite:
    runs-on: ubuntu-latest
    
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
      
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt
          pip install pytest pytest-cov
      
      - name: Run DSL v2 test suite
        run: pytest tests/test_dsl_v2_validation.py -v --cov=scripts --cov-report=term
      
      - name: Upload coverage
        uses: codecov/codecov-action@v3
        if: always()
        with:
          files: ./coverage.xml
          flags: dsl-v2
```

---

### Alternative CI (GitLab)

**File:** `.gitlab-ci.yml`

```yaml
dsl-v2-checks:
  stage: test
  image: python:3.11
  before_script:
    - pip install -r requirements.txt
    - pip install jsonschema pyyaml pytest click
  script:
    - make dsl.validate
    - make dsl.lint
    - make test
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
      changes:
        - examples/**/*.yaml
        - tests/fixtures/**/*.yaml
        - scripts/validate_dsl_v2.py
        - scripts/lint_dsl_v2.py
```

---

## 5.5 Migration Cookbook (Copy-Paste Codemods & Patterns)

### A) `tool: iterator` → `loop` + `tool`

**Before:**
```yaml
- step: users
  tool: iterator
  collection: "{{ workload.users }}"
  element: user
  mode: parallel
  task:
    tool: playbook
    path: tests/fixtures/playbooks/user_profile_scorer
    args: { user_data: "{{ user }}" }
    sink:
      table: public.user_profile_results
      key: id
      args: { id: "{{ execution_id }}:{{ user.name }}" }
```

**After:**
```yaml
- step: users
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  tool:
    kind: playbook
    spec:
      path: tests/fixtures/playbooks/user_profile_scorer
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
- `loop` block created at step level
- Nested `task` flattened into `tool`
- `save` converted to `result.sink` list
- `storage` field removed (inferred from sink key)

---

### B) Step-Level `args` / `save` → `tool.args` / `tool.result.sink`

**Before:**
```yaml
- step: load
  tool: postgres
  args:
    query: "select * from users"
  sink:
    tool: duckdb
    file: ./users.duckdb
    table: users
```

**After:**
```yaml
- step: load
  tool:
    kind: postgres
    spec: {}
    args:
      query: "select * from users"
    result:
      sink:
        - duckdb:
            file: ./users.duckdb
            table: users
```

**Changes:**
- Scalar `tool: postgres` wrapped in object with `kind` and `spec`
- `args` moved under `tool`
- `save` converted to `result.sink` list
- `storage` field removed (redundant with sink key)

---

### C) Scalar `next` → Edge List

**Before:**
```yaml
- step: route
  next: final
```

**After:**
```yaml
- step: route
  next:
    - step: final
```

**Changes:**
- Scalar string converted to array
- Entry is object with `step` key

---

### D) Branching (if/elif/else)

**Before:**
```yaml
- step: route
  next:
    - when: "{{ score > 0.8 }}"
      step: high
    - when: "{{ score > 0.5 }}"
      step: mid
    - step: low
```

**After (unchanged structurally):**
```yaml
- step: route
  next:
    - when: "{{ score > 0.8 }}"
      step: high
    - when: "{{ score > 0.5 }}"
      step: mid
    - step: low  # Else (no when)
```

**Notes:**
- Keep order (if/elif/else semantics)
- Single else (at most one edge without `when`)
- First matching edge is taken

---

### E) AND-Join Without Dependencies (Use Helpers)

**Join step:**
```yaml
- step: join
  desc: "Wait for both A and B; require B success"
  when: "{{ done('A') and ok('B') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {"combined": context["A_result"] + context["B_result"]}
    result:
      as: joined_result
  next:
    - step: finalize
```

**Helper alternatives:**
```yaml
# Wait for all
when: "{{ all_done(['A', 'B', 'C']) }}"

# Wait for any
when: "{{ any_done(['A', 'B', 'C']) }}"

# Wait for completion regardless of success
when: "{{ done('A') and done('B') }}"

# Require all success
when: "{{ ok('A') and ok('B') }}"

# Wait for loop drain
when: "{{ loop_done('process_users') }}"
```

---

### F) Collect Results During Loop

**Add `collect` and use later:**

```yaml
- step: proc_users
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  tool:
    kind: playbook
    spec:
      path: tests/fixtures/playbooks/user_profile_scorer
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
      scores: "{{ all_scores }}"  # Use collected results
```

**Collect modes:**
```yaml
# List mode (default)
collect:
  into: all_results
  mode: list

# Map mode (keyed by expression)
collect:
  into: user_map
  mode: map
  key: "{{ out.user_id }}"
```

---

### G) Multi-Sink Fan-Out

**Fan-out to multiple destinations:**

```yaml
tool:
  kind: python
  spec:
    code: |
      def main(context, results):
          return {"id": context["user_id"], "score": 0.85}
  result:
    sink:
      - postgres:
          table: scores
          key: id
          args:
            id: "{{ out.id }}"
            score: "{{ out.score }}"
      - s3:
          bucket: "noetl-data-lake"
          key: "scores/{{ out.id }}.json"
      - file:
          path: "/tmp/scores/{{ out.id }}.json"
```

**Notes:**
- `sink` is always a list
- Each entry is single-key object (sink type)
- All sinks receive same `out` data
- Sinks execute in order (sequential)

---

### H) Reserve Engine Namespace (Avoid Collisions)

**❌ Don't do this:**
```yaml
# Bad: writing to reserved namespace
bind:
  step: "my_value"  # ERROR: step is reserved

tool:
  result:
    as: step  # ERROR: step is reserved
```

**✅ Do this instead:**
```yaml
# Good: use unique names
bind:
  step_data: "my_value"

tool:
  result:
    as: step_result

# Read status with helpers
when: "{{ done('step_id') }}"

# Or access status namespace directly
when: "{{ step.step_id.status.done }}"
```

**Reserved namespace:**
- `step.*` - Engine-managed status
- `step.<id>.status.*` - Step execution status
- Helper functions access this namespace

---

## 5.6 Sample "Refactor PR" Body

**Copy-paste template for your migration PR:**

```markdown
## Scope
Migrate workflows to DSL v2: `loop/tool/next` + `result.sink` (list)

### Key Changes
- Replace `tool: iterator` and nested `task:` with canonical structure
- Introduce helpers in guards: `done()/ok()/loop_done()`
- Move step-level `args`/`save` under `tool`

---

## Changes

### Automated Migrations
Ran codemod:
```bash
python scripts/codemod_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml
```

### Manual Adjustments
- Added `result.as` for downstream consumption:
  - `user_raw` (fetch_user step)
  - `user_score` (score_user step)
  - `user_profile` (join step)
- Added `collect.into: all_scores` in loop steps where reducers consume aggregates
- Refactored guards to use engine helpers:
  - `when: "{{ done('fetch_user') and ok('score_user') }}"`
  - `when: "{{ loop_done('proc_users') }}"`
- Updated fixtures with new patterns (fanout_and_join, loop_reduce)

### Files Modified
- `examples/user_processor.yaml`
- `examples/batch_scorer.yaml`
- `tests/fixtures/workflows/v2/valid/fanout_and_join.yaml` (new)
- `tests/fixtures/workflows/v2/valid/loop_reduce.yaml` (new)
- `tests/fixtures/workflows/v2/invalid/*.yaml` (new negative cases)

---

## Validation

### Local Checks
```bash
make dsl.validate  # ✅ PASS
make dsl.lint      # ✅ PASS
make test          # ✅ PASS (127/127 tests passed)
```

### CI Status
- Schema validation: ✅
- Semantic linting: ✅
- Test suite: ✅
- Legacy construct check: ✅

---

## Testing

### New Tests Added
- `test_valid_fixtures_pass_schema()` - Golden fixtures validation
- `test_invalid_fixtures_fail_lint()` - Negative case detection
- `test_bad_top_level_keys_detected()` - Extra keys rejection
- `test_iterator_as_tool_detected()` - Legacy iterator detection
- `test_multiple_else_edges_detected()` - Next edge constraints

### Coverage
- All existing e2e tests pass
- New DSL v2 validation suite: 10/10 tests passing
- Golden fixtures: 3 valid patterns
- Negative fixtures: 6 invalid patterns

---

## Notes

### Migration Statistics
- Files migrated: 15
- Automated: 12 (codemod)
- Manual: 3 (semantic enhancements)
- Lines changed: ~500

### Known Issues
None. All validation checks pass.

### Follow-Up Tasks
- [ ] Update documentation with new patterns
- [ ] Add more golden fixtures for complex patterns
- [ ] Create video tutorial for DSL v2

### Rollback Plan
- Git tag: `pre-dsl-v2` created before migration
- Revert command: `git reset --hard pre-dsl-v2`
- Codemod is idempotent (safe to re-run)

---

**Ready for review!** 🚀
```

---

## 5.7 Quick "Failure Dictionary"

**What red errors likely mean and how to fix them:**

---

### Error: `"tool: iterator is invalid"`

**Cause:** Using legacy `tool: iterator` construct

**Fix:**
1. Create `loop` block at step level
2. Move `collection`, `element`, `mode` under `loop`
3. Remove `tool: iterator`
4. If nested `task` exists, flatten into `tool`

**Example:**
```yaml
# Before
tool: iterator
collection: "{{ items }}"
element: item

# After
loop:
  collection: "{{ items }}"
  element: item
```

---

### Error: `"result.sink must be a list"`

**Cause:** `sink` is object instead of array

**Fix:**
1. Wrap sink map in array
2. Ensure each array item has single key (sink id)

**Example:**
```yaml
# Before
result:
  sink:
    postgres: { table: t }

# After
result:
  sink:
    - postgres: { table: t }
```

---

### Error: `"Unknown top-level keys"` or `"Additional properties are not allowed"`

**Cause:** Keys outside `{step, desc, when, bind, loop, tool, next}` at step level

**Fix:**
1. Move plugin-specific keys into `tool.spec`
2. Move `args` under `tool`
3. Move `save` to `tool.result.sink`

**Example:**
```yaml
# Before
step: fetch
method: GET          # Wrong level
endpoint: "/api"     # Wrong level
args: {}             # Wrong level

# After
step: fetch
tool:
  kind: http
  spec:
    method: GET
    endpoint: "/api"
  args: {}
```

---

### Error: `"More than one else edge"` or `"next may contain at most one edge without 'when'"`

**Cause:** Multiple `next` edges without `when` condition

**Fix:**
1. Keep only one edge without `when` (final else)
2. Add `when` conditions to all other edges

**Example:**
```yaml
# Before
next:
  - step: A     # else 1
  - step: B     # else 2 (ERROR)

# After
next:
  - when: "{{ condition }}"
    step: A
  - step: B     # Only one else
```

---

### Error: `"Reserved namespace violation: step"`

**Cause:** Attempting to write to `step` via `bind` or `result.as`

**Fix:**
1. Use different name (not `step`)
2. Access status via helpers or `step.<id>.status.*`

**Example:**
```yaml
# Before
bind:
  step: value        # ERROR

result:
  as: step          # ERROR

# After
bind:
  step_data: value

result:
  as: step_result

# Read status with helpers
when: "{{ done('step_id') }}"
```

---

### Error: `"'path' is a required property"` (playbook)

**Cause:** Missing required fields in plugin spec

**Fix:** Add required fields for plugin type

**Examples:**
```yaml
# Playbook requires path
tool:
  kind: playbook
  spec:
    path: playbooks/my_playbook  # Required

# Workbook requires name
tool:
  kind: workbook
  spec:
    name: my_task  # Required

# HTTP requires method and endpoint
tool:
  kind: http
  spec:
    method: GET      # Required
    endpoint: "/api" # Required

# Postgres requires query
tool:
  kind: postgres
  spec:
    query: "SELECT *"  # Required

# Python requires code OR (module + callable)
tool:
  kind: python
  spec:
    code: "def main(): ..."  # Option 1
    # OR
    module: "my_module"      # Option 2
    callable: "my_function"  # Option 2
```

---

### Error: `"collect.mode: map requires key"`

**Cause:** Using `collect.mode: map` without `collect.key`

**Fix:** Add `key` expression for map mode

**Example:**
```yaml
# Before
collect:
  into: user_map
  mode: map        # ERROR: missing key

# After
collect:
  into: user_map
  mode: map
  key: "{{ out.user_id }}"
```

---

### Error: `"result.sink[0] must have exactly one key (sink id)"`

**Cause:** Sink entry has multiple keys or no keys

**Fix:** Each sink entry must be single-key map

**Example:**
```yaml
# Before
sink:
  - postgres:
      table: t
    s3:              # ERROR: two keys in same entry
      bucket: b

# After
sink:
  - postgres:
      table: t
  - s3:
      bucket: b
```

---

## 5.8 Rollback/Rerun Strategy

### Pre-Migration Tag

**Before running codemods, create safety tag:**

```bash
# Create tag
git tag pre-dsl-v2

# Push tag
git push origin pre-dsl-v2

# Verify tag exists
git tag -l pre-dsl-v2
```

---

### Rollback Options

**Option 1: Hard reset (complete revert)**
```bash
# Revert to pre-migration state
git reset --hard pre-dsl-v2

# Force push if already pushed
git push origin master --force
```

**Option 2: Revert commit (preserve history)**
```bash
# Find migration commit
git log --oneline

# Revert specific commit
git revert <commit-sha>

# Push revert
git push origin master
```

**Option 3: Selective rollback (specific files)**
```bash
# Checkout specific files from tag
git checkout pre-dsl-v2 -- examples/my_workflow.yaml

# Re-run codemod
python scripts/codemod_dsl_v2.py examples/my_workflow.yaml

# Commit
git commit -m "Re-migrate my_workflow.yaml"
```

---

### Re-Run Codemod (Idempotent)

**Codemods are safe to re-run:**

```bash
# Re-run on all files (idempotent)
python scripts/codemod_dsl_v2.py examples/**/*.yaml tests/fixtures/**/*.yaml

# Or use make target
make dsl.codemod

# Verify changes
git diff

# Re-validate
make dsl.validate
make dsl.lint
```

**Why idempotent:**
- Detects already-migrated patterns
- No changes if already compliant
- Safe to run multiple times

---

### Reverse Script (Optional)

**Create reverse codemod if needed:**

**File:** `scripts/codemod_dsl_v2_reverse.py`

```python
#!/usr/bin/env python3
"""
DSL v2 Reverse Codemod (Optional)

Re-expands tool to step-level fields for selective rollback.
Use with caution - prefer Git revert instead.
"""
import sys, yaml, pathlib

def reverse_transform(step):
    """Reverse DSL v2 transforms"""
    if "tool" in step and isinstance(step["tool"], dict):
        tool = step["tool"]
        
        # Extract args to step level (if simple)
        if "args" in tool and not step.get("loop"):
            step["args"] = tool.pop("args")
        
        # Extract result.sink to step-level save (if single sink)
        if "result" in tool and "sink" in tool["result"]:
            sinks = tool["result"]["sink"]
            if len(sinks) == 1:
                sink_entry = sinks[0]
                sink_type = list(sink_entry.keys())[0]
                step["save"] = sink_entry[sink_type]
                step["save"]["storage"] = sink_type
        
        # Simplify scalar tool if possible
        if tool.get("spec") == {} and not tool.get("result"):
            step["tool"] = tool.get("kind")

def main(paths):
    for p in map(pathlib.Path, paths):
        data = yaml.safe_load(p.read_text())
        steps = data.get("workflow") if isinstance(data, dict) else data
        
        for step in steps:
            reverse_transform(step)
        
        p.write_text(yaml.safe_dump(data, sort_keys=False))
        print(f"REVERSED {p}")

if __name__ == "__main__":
    main(sys.argv[1:])
```

**Usage:**
```bash
python scripts/codemod_dsl_v2_reverse.py examples/my_workflow.yaml
```

**Note:** Prefer Git revert; this is for edge cases only.

---

## Summary

This document provides:

1. **Makefile targets** for one-liner automation
2. **CLI commands** with Click-based interface
3. **PR template** with DSL v2 checklist
4. **CI integration** (GitHub Actions + GitLab)
5. **Migration cookbook** with 8 copy-paste patterns
6. **Sample PR body** for refactor PRs
7. **Failure dictionary** for common errors
8. **Rollback strategy** with tag-based safety

---

**Next Steps:**
- Wire Makefile targets into existing build system
- Create CLI entry point in project root
- Add PR template to repository
- Configure CI pipeline
- Test migration on sample workflows

---

**Ready for next portion of the refactoring plan.**
