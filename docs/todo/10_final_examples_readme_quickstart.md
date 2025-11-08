# Final Examples, README Text, One-Page Quickstart

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Provide production-ready examples, documentation snippets, and quickstart guide for DSL v2 adoption

---

## 10.1 End-to-End Examples (Golden)

**Location:** `examples/workflows/v2/`

---

### A) Fan-out, Join, Persist

**File:** `examples/workflows/v2/fanout_join_persist.yaml`

```yaml
# Fan-out to parallel tasks, AND-join, persist result
# Demonstrates: parallel dispatch, conditional join, sink fan-out

- step: start
  desc: "Entry point"
  next:
    - step: fetch_user
    - step: score_user

- step: fetch_user
  desc: "Fetch user profile from API"
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "{{ base }}/users/{{ workload.user_id }}"
      headers:
        Authorization: "{{ secrets.api_token }}"
    result:
      as: user_raw
  next:
    - step: join

- step: score_user
  desc: "Score user via playbook"
  tool:
    kind: playbook
    spec:
      path: tests/fixtures/playbooks/user_profile_scorer
      return_step: finalize_result
    args:
      user: "{{ user_raw }}"
    result:
      as: user_score
  next:
    - step: join

- step: join
  desc: "AND-join; proceed when both predecessors are done and scoring succeeded"
  when: "{{ done('fetch_user') and ok('score_user') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            u, s = context["user_raw"], context["user_score"]
            return {
                "id": u["id"],
                "name": u["name"],
                "score": s["value"]
            }
    result:
      as: user_profile
      sink:
        - postgres:
            auth: "{{ workload.pg_auth }}"
            table: public.user_profiles
            mode: upsert
            key: id
            args:
              id: "{{ user_profile.id }}"
              name: "{{ user_profile.name }}"
              score: "{{ user_profile.score }}"
  next:
    - step: done

- step: done
  desc: "Terminal step"
```

**Key Patterns:**
- Parallel fan-out via multiple `next` targets
- AND-join with `when: "{{ done('A') and ok('B') }}"`
- Sink fan-out (postgres) with upsert mode

---

### B) Loop + Collect + Reduce

**File:** `examples/workflows/v2/loop_collect_reduce.yaml`

```yaml
# Loop over collection, collect results, reduce to summary
# Demonstrates: loop controller, collect, loop_done gate

- step: start
  next:
    - step: proc_users

- step: proc_users
  desc: "Loop over users as 'user' and run sub-playbook"
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
      pick: "{{ {'name': user.name, 'score': this.profile_score or 0.0, 'cat': this.score_category or 'unknown'} }}"
      as: last_score
      collect:
        into: all_scores
        mode: list
      sink:
        - postgres:
            auth: "{{ workload.pg_auth }}"
            table: public.user_profile_results
            mode: upsert
            key: id
            args:
              id: "{{ execution_id }}:{{ out.name }}"
              user_name: "{{ out.name }}"
              profile_score: "{{ out.score }}"
              score_category: "{{ out.cat }}"
  next:
    - step: summarize

- step: summarize
  desc: "Wait for loop to finish; compute aggregate"
  when: "{{ loop_done('proc_users') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            scores = context.get("all_scores", [])
            avg = sum(x["score"] for x in scores) / len(scores) if scores else 0
            top = max(scores, key=lambda x: x["score"]) if scores else None
            return {
                "count": len(scores),
                "avg": avg,
                "top": top
            }
    result:
      as: scores_summary
      sink:
        - file:
            path: "/tmp/scores_summary_{{ execution_id }}.json"
```

**Key Patterns:**
- Loop with `mode: parallel`
- `result.pick` for shaping output
- `result.collect` for accumulation
- `when: "{{ loop_done('proc_users') }}"` gate for reducer
- Multiple sinks per item (postgres) and final summary (file)

---

### C) Postgres → DuckDB Staging → S3 Fan-out

**File:** `examples/workflows/v2/pg_to_duck_to_s3.yaml`

```yaml
# Extract from Postgres, stage in DuckDB, export to S3
# Demonstrates: data pipeline, sink chaining, conditional next

- step: extract
  desc: "Extract from Postgres"
  tool:
    kind: postgres
    spec:
      query: |
        SELECT id, name, updated_at, score
        FROM public.users
        WHERE updated_at >= {{ workload.since }}
      auth: "{{ workload.pg_auth }}"
    result:
      as: users
      sink:
        - duckdb:
            file: "./stage.duckdb"
            table: users
  next:
    - step: export

- step: export
  desc: "Export staged table to S3"
  when: "{{ ok('extract') }}"
  tool:
    kind: duckdb
    spec:
      file: "./stage.duckdb"
      query: |
        COPY (SELECT * FROM users) 
        TO '{{ workload.s3_uri }}/users.parquet' 
        (FORMAT parquet);
    result:
      sink:
        - s3:
            bucket: "{{ workload.s3_bucket }}"
            key: "exports/users_{{ execution_id }}.parquet"
            acl: private
```

**Key Patterns:**
- Data pipeline flow (postgres → duckdb → s3)
- Intermediate sink (duckdb staging)
- Final sink (s3 export)
- Conditional next with `when: "{{ ok('extract') }}"`

---

### D) Router-Only Step (No Tool), If/Elif/Else

**File:** `examples/workflows/v2/router_branches.yaml`

```yaml
# Pure routing step with if/elif/else branches
# Demonstrates: router pattern, ordered edge evaluation

- step: start
  desc: "Route by feature flags"
  next:
    - when: "{{ workload.feature_x_enabled }}"
      step: path_x
    - when: "{{ workload.feature_y_enabled }}"
      step: path_y
    - step: fallback  # Else (no when)

- step: path_x
  desc: "Feature X path"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {"path": "x", "feature": "feature_x"}
    result:
      as: path

- step: path_y
  desc: "Feature Y path"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {"path": "y", "feature": "feature_y"}
    result:
      as: path

- step: fallback
  desc: "Fallback path (default)"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {"path": "fallback", "feature": "none"}
    result:
      as: path
```

**Key Patterns:**
- Pure router (start has no tool)
- Ordered edge evaluation (if/elif/else)
- Last edge without `when` is else branch

---

## 10.2 README Drop-ins (Copy/Paste Sections)

---

### Section: "Workflow DSL v2 at a Glance"

```markdown
## Workflow DSL v2 at a Glance

**Top-level step keys (4 chars):** `step`, `desc`, `when`, `bind`, `loop`, `tool`, `next`

### Core Concepts

- **Step gate** — `when`: step runs *only when called* and the condition is truthy
- **Loop** — `loop: { collection, element, mode?, until? }` (controller; not a tool)
- **Tool** — `tool: { kind, spec, args?, result? }` (actionable unit)
- **Result** — shape/output handling:
  - `as`: put shaped result into context
  - `pick`: compute `out` from `this`
  - `sink`: **list** of single-key objects (fan-out)
  - `collect`: accumulate results in loops (`{ into, mode: list|map, key? }`)
- **Routing** — `next`: ordered edges `{ step, when? }` (if/elif/else)

### Helpers (Jinja)

`done('id')`, `ok('id')`, `fail('id')`, `running('id')`, `loop_done('id')`, `all_done([...])`, `any_done([...])`

### Reserved Namespace

`step.<id>.status.*` (engine-managed, read-only)

### Example

```yaml
- step: process_users
  when: "{{ done('fetch_users') }}"
  loop:
    collection: "{{ workload.users }}"
    element: user
    mode: parallel
  tool:
    kind: playbook
    spec:
      path: playbooks/score_user
    args:
      user: "{{ user }}"
    result:
      pick: "{{ {'name': user.name, 'score': this.score} }}"
      collect:
        into: all_scores
        mode: list
      sink:
        - postgres:
            table: results
            mode: upsert
            key: id
  next:
    - step: summarize
```
```

---

### Section: "Author Cheatsheet"

```markdown
## Author Cheatsheet

### Common Patterns

**AND-join:**
```yaml
when: "{{ done('A') and ok('B') }}"
```

**Loop fan-out:**
```yaml
loop:
  collection: "{{ items }}"
  element: item
  mode: parallel
```

**Persist to many:**
```yaml
result:
  sink:
    - postgres: { table: t, mode: upsert, key: id }
    - s3: { bucket: b, key: "data.json" }
    - file: { path: "/tmp/out.json" }
```

**Last item:**
```yaml
result:
  as: last_item
```

**All items (loop):**
```yaml
result:
  collect:
    into: all_items
    mode: list
```

**Else branch:**
```yaml
next:
  - when: "{{ condition_a }}"
    step: path_a
  - when: "{{ condition_b }}"
    step: path_b
  - step: fallback  # Else (no when)
```

### Rules

- **Only these step keys:** `step`, `desc`, `when`, `bind`, `loop`, `tool`, `next`
- **No legacy fields:** No `tool: iterator`, no step-level `args`/`save`, no nested `task`
- **Sinks are lists:** Each sink is a single-key object (e.g., `postgres: {...}`)
- **Use helpers for joins:** `done()`, `ok()`, `loop_done()`
- **Don't write to `step.*`** — it's engine-managed
```

---

### Section: "Migration Cliff-Notes (v1 → v2)"

```markdown
## Migration Cliff-Notes (v1 → v2)

### Quick Migration Steps

1. **Replace `tool: iterator`** with step-level `loop`
   ```yaml
   # OLD (v1)
   tool: iterator
   over: "{{ items }}"
   
   # NEW (v2)
   loop:
     collection: "{{ items }}"
     element: item
   ```

2. **Move step-level `args`/`save`** → `tool.args` / `tool.result.sink` (list)
   ```yaml
   # OLD (v1)
   - step: fetch
     type: http
     args: { url: "..." }
     save: { storage: postgres, table: t }
   
   # NEW (v2)
   - step: fetch
     tool:
       kind: http
       spec: { url: "..." }
       result:
         sink:
           - postgres: { table: t }
   ```

3. **Flatten nested `task:` blocks** into `tool: { kind, spec, args, result }`
   ```yaml
   # OLD (v1)
   task:
     type: http
     spec: { url: "..." }
   
   # NEW (v2)
   tool:
     kind: http
     spec: { url: "..." }
   ```

4. **Make `next` a list** of `{ step, when? }` (ordered). At most one else.
   ```yaml
   # OLD (v1)
   next: next_step
   
   # NEW (v2)
   next:
     - step: next_step
   ```

5. **Use helpers in `when`** instead of hand-rolled flags
   ```yaml
   # OLD (v1)
   when: "{{ context.step_a_done and context.step_a_ok }}"
   
   # NEW (v2)
   when: "{{ done('step_a') and ok('step_a') }}"
   ```

### Automated Migration

Use the codemod script:
```bash
python scripts/codemod_dsl_v2.py examples/my_workflow.yaml --in-place
```

Validate after migration:
```bash
make dsl.validate
make dsl.lint
```
```

---

## 10.3 One-Page Quickstart (Hand to Authors)

**File:** `docs/quickstart_dsl_v2.md`

```markdown
# NoETL Workflow Quickstart (DSL v2)

## 1) Minimal "hello"

```yaml
- step: start
  next:
    - step: hello

- step: hello
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {"msg": "hello world"}
    result:
      as: hello_msg
```

---

## 2) Loop over data

```yaml
- step: proc_items
  loop:
    collection: "{{ workload.items }}"
    element: item
    mode: sequential
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {
                "id": context["item"]["id"],
                "val": 1
            }
    result:
      pick: "{{ {'id': item.id, 'val': this.val} }}"
      as: last_item
      collect:
        into: all_items
        mode: list
```

---

## 3) Branching

```yaml
- step: route
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {}
  next:
    - when: "{{ workload.mode == 'fast' }}"
      step: fast_path
    - step: slow_path  # Else
```

---

## 4) Join after fan-out

```yaml
- step: start
  next:
    - step: A
    - step: B

- step: A
  tool:
    kind: http
    spec:
      url: "https://api.example.com/a"

- step: B
  tool:
    kind: http
    spec:
      url: "https://api.example.com/b"

- step: C
  when: "{{ done('A') and ok('B') }}"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            return {"merged": "data"}
```

---

## 5) Persist results (fan-out sinks)

```yaml
tool:
  kind: python
  spec:
    code: |
      def main(context, results):
          return {"id": 123, "name": "Alice"}
  result:
    as: out
    sink:
      - postgres:
          table: users
          mode: upsert
          key: id
          args:
            id: "{{ out.id }}"
            name: "{{ out.name }}"
      - file:
          path: "/tmp/out_{{ execution_id }}.json"
```

---

## Rules of Thumb

1. **Only these step keys:** `step`, `desc`, `when`, `bind`, `loop`, `tool`, `next`

2. **`tool.kind` + `tool.spec`** define what, **`tool.args`** provide inputs

3. **Use helpers for joins:** `done()`, `ok()`, `loop_done()`

4. **Sinks are a list:** each item is a single-key object (e.g., `postgres: {...}`)

5. **Don't write to `step.*`** — it's engine-managed

---

## Next Steps

- See `examples/workflows/v2/` for complete patterns
- Read `docs/dsl_spec.md` for full specification
- Run `make dsl.validate` to check your workflow
- Run `make dsl.lint` for best-practice warnings

---

## Getting Help

- Cheat sheet: `docs/author_cheatsheet.md`
- Migration guide: `docs/migration_v1_to_v2.md`
- Troubleshooting: `docs/troubleshooting.md`
```

---

## 10.4 Final "Ready-to-Ship" README Header (Copy Verbatim)

**File:** `README.md` (header section)

```markdown
# NoETL Workflow DSL v2

NoETL's v2 workflow DSL separates **control-plane** from **data-plane**:

- **Step (control)** — orchestrates: `when`, `loop`, `next`
- **Tool (data)** — does work: `kind`, `spec`, `args`, `result`

This yields clean fan-out/fan-in, Petri-net style joins via:

```yaml
when: "{{ done('A') and ok('B') }}"
```

Outputs are shaped and persisted with:

```yaml
tool:
  result:
    as: my_result
    pick: "{{ {'id': this.id, 'score': this.score} }}"
    sink:
      - postgres:
          table: t
          key: id
          args:
            id: "{{ my_result.id }}"
```

**Top-level step keys (4 chars):** `step`, `desc`, `when`, `bind`, `loop`, `tool`, `next`

See `/examples/workflows/v2` for canonical patterns:

- `fanout_join_persist.yaml` — Parallel fan-out, AND-join, sink fan-out
- `loop_collect_reduce.yaml` — Loop over collection, collect, reduce
- `pg_to_duck_to_s3.yaml` — Data pipeline (Postgres → DuckDB → S3)
- `router_branches.yaml` — Pure routing with if/elif/else

---

## Quick Start

```bash
# Install
pip install noetl

# Validate workflow
noetl validate examples/workflows/v2/fanout_join_persist.yaml

# Run workflow
noetl run examples/workflows/v2/fanout_join_persist.yaml --workload workload.json

# Check status
noetl status <execution_id>
```

---

## Documentation

- **Quickstart:** `docs/quickstart_dsl_v2.md`
- **Full Spec:** `docs/dsl_spec.md`
- **Migration Guide:** `docs/migration_v1_to_v2.md`
- **Author Cheatsheet:** `docs/author_cheatsheet.md`
- **API Reference:** `docs/api_usage.md`

---

## Features

- ✅ Petri-net execution model (call semantics, gates, joins)
- ✅ Loop controller with parallel/sequential modes
- ✅ Result shaping with `pick`, `as`, `collect`, `sink`
- ✅ Sink fan-out (postgres, s3, file, duckdb, kafka)
- ✅ Exactly-once sink guarantees (ledger-based)
- ✅ Jinja helpers for control flow (`done()`, `ok()`, `loop_done()`)
- ✅ OpenTelemetry tracing and Prometheus metrics
- ✅ Retry/backoff/DLQ with idempotency keys
- ✅ Canary rollout and chaos testing

---
```

---

## 10.5 Final Sanity Check List (Paste Near CI)

**File:** `.github/workflows/ci.yml` (comment or checklist section)

```yaml
# ===== DSL v2 Sanity Checks =====
# Run before merging DSL v2 changes

# Checklist:
# [ ] All examples validate (schema + lint)
# [ ] No legacy fields (tool: iterator, step-level args/save, nested task)
# [ ] Sinks are lists of single-key objects
# [ ] Docs reference helpers: done(), ok(), loop_done()
# [ ] 4-char step keys respected end-to-end
# [ ] Golden fixtures green (tests/fixtures/dsl_v2/)
# [ ] Negative fixtures fail correctly
# [ ] Migration codemod tested on all examples
# [ ] README snippets render correctly
# [ ] Quickstart guide tested end-to-end

- name: Validate DSL v2 Examples
  run: |
    make dsl.validate-examples
    make dsl.lint-examples

- name: Check for Legacy Fields
  run: |
    # Fail if any example contains legacy patterns
    ! grep -r "tool: iterator" examples/workflows/v2/
    ! grep -r "^  args:" examples/workflows/v2/  # Step-level args
    ! grep -r "^  save:" examples/workflows/v2/  # Step-level save

- name: Validate Sink Format
  run: |
    # Ensure all sinks are lists
    python scripts/validate_sink_format.py examples/workflows/v2/

- name: Test Golden Fixtures
  run: |
    pytest tests/fixtures/dsl_v2/ -v

- name: Test Migration Codemod
  run: |
    # Test codemod on examples
    python scripts/codemod_dsl_v2.py examples/workflows/v1/sample.yaml --dry-run
    # Verify output matches expected
    diff <(python scripts/codemod_dsl_v2.py examples/workflows/v1/sample.yaml --dry-run) \
         tests/fixtures/codemod/expected_output.yaml

- name: Render README Snippets
  run: |
    # Ensure README markdown renders correctly
    python -m markdown_include.include README.md > /tmp/readme_rendered.html
    # Check for broken links
    linkchecker /tmp/readme_rendered.html

- name: Test Quickstart Guide
  run: |
    # Run quickstart examples end-to-end
    noetl validate docs/quickstart_dsl_v2.md --extract-yaml
    noetl run docs/quickstart_dsl_v2.md --extract-yaml --example 1
    noetl run docs/quickstart_dsl_v2.md --extract-yaml --example 2
```

---

**Makefile Targets:**

```makefile
# File: Makefile

.PHONY: dsl.validate-examples dsl.lint-examples dsl.sanity-check

dsl.validate-examples:
	@echo "Validating DSL v2 examples..."
	@for file in examples/workflows/v2/*.yaml; do \
		echo "Validating $$file..."; \
		python scripts/validate_dsl_v2.py $$file || exit 1; \
	done
	@echo "✅ All examples valid"

dsl.lint-examples:
	@echo "Linting DSL v2 examples..."
	@for file in examples/workflows/v2/*.yaml; do \
		echo "Linting $$file..."; \
		python scripts/lint_dsl_v2.py $$file || exit 1; \
	done
	@echo "✅ All examples lint-clean"

dsl.sanity-check: dsl.validate-examples dsl.lint-examples
	@echo "Running sanity checks..."
	@echo "Checking for legacy fields..."
	@! grep -r "tool: iterator" examples/workflows/v2/ || (echo "❌ Found legacy 'tool: iterator'" && exit 1)
	@! grep -r "^  args:" examples/workflows/v2/ || (echo "❌ Found step-level 'args'" && exit 1)
	@! grep -r "^  save:" examples/workflows/v2/ || (echo "❌ Found step-level 'save'" && exit 1)
	@echo "Validating sink format..."
	@python scripts/validate_sink_format.py examples/workflows/v2/
	@echo "✅ Sanity checks passed"
```

---

## 10.6 Complete File Tree (Reference)

```
noetl/
├── examples/
│   └── workflows/
│       └── v2/
│           ├── fanout_join_persist.yaml
│           ├── loop_collect_reduce.yaml
│           ├── pg_to_duck_to_s3.yaml
│           └── router_branches.yaml
├── docs/
│   ├── quickstart_dsl_v2.md
│   ├── dsl_spec.md
│   ├── migration_v1_to_v2.md
│   ├── author_cheatsheet.md
│   └── todo/
│       ├── 01_dsl_refactoring_overview.md
│       ├── 02_migration_strategy_and_codemods.md
│       ├── 03_schema_validation_and_linter.md
│       ├── 04_test_fixtures_runner_readme.md
│       ├── 05_cli_makefile_pr_ci_cookbook.md
│       ├── 06_editor_snippets_diagnostics_ergonomics.md
│       ├── 07_implementation_tasks_rollout.md
│       ├── 08_observability_retries_timeouts_compensation.md
│       ├── 09_hardening_idempotency_concurrency_chaos.md
│       └── 10_final_examples_readme_quickstart.md
├── scripts/
│   ├── validate_dsl_v2.py
│   ├── lint_dsl_v2.py
│   ├── codemod_dsl_v2.py
│   ├── jinja_helpers.py
│   └── validate_sink_format.py
├── tests/
│   ├── fixtures/
│   │   └── dsl_v2/
│   │       ├── golden/
│   │       │   ├── fanout_join.yaml
│   │       │   ├── loop_reduce.yaml
│   │       │   └── http_simple.yaml
│   │       └── negative/
│   │           ├── bad_top_level_keys.yaml
│   │           ├── iterator_as_tool.yaml
│   │           └── bad_sink_shape.yaml
│   └── chaos/
│       ├── test_exactly_once.py
│       ├── test_dup_delivery.py
│       ├── test_backpressure.py
│       ├── test_server_restart.py
│       └── test_dlq_replay.py
├── README.md
├── Makefile
└── .github/
    └── workflows/
        └── ci.yml
```

---

## 10.7 Deployment Readiness Checklist

**Pre-Launch:**

- [ ] All 4 golden examples validate and execute end-to-end
- [ ] Quickstart guide tested by external user (feedback incorporated)
- [ ] README header renders correctly on GitHub
- [ ] Migration codemod tested on 10+ legacy workflows
- [ ] Negative fixtures correctly rejected by validator
- [ ] CI sanity checks passing
- [ ] Documentation links all resolve
- [ ] Cheat sheet printed and distributed to team

**Launch:**

- [ ] Tag release: `v2.0.0-rc1`
- [ ] Announce in Slack/Discord/Mailing list
- [ ] Blog post with quickstart walkthrough
- [ ] Update homepage with DSL v2 features
- [ ] Migration deadline announced (3 months)

**Post-Launch:**

- [ ] Monitor adoption metrics (% of workflows using v2)
- [ ] Collect feedback (GitHub issues, surveys)
- [ ] Iterate on documentation (FAQ, troubleshooting)
- [ ] Plan deprecation timeline for v1 (6 months)

---

## Summary

**Portion 10 deliverables:**

1. **4 golden examples** (`examples/workflows/v2/`)
   - Fan-out, join, persist
   - Loop, collect, reduce
   - Postgres → DuckDB → S3 pipeline
   - Router branches (if/elif/else)

2. **3 README drop-in sections**
   - "Workflow DSL v2 at a Glance"
   - "Author Cheatsheet"
   - "Migration Cliff-Notes"

3. **One-page quickstart** (`docs/quickstart_dsl_v2.md`)
   - 5 minimal examples
   - Rules of thumb
   - Next steps and help

4. **README header** (copy verbatim for main README)
   - Control vs data plane separation
   - Quick start commands
   - Feature checklist

5. **CI sanity checks** (paste in `.github/workflows/ci.yml`)
   - Validate examples
   - Check for legacy fields
   - Validate sink format
   - Test golden fixtures
   - Test codemod

6. **Makefile targets** for automation
7. **Complete file tree** reference
8. **Deployment readiness checklist**

---

**Total documentation: ~1,000 lines**

This completes the **10-part DSL v2 refactoring guide** (~16,000 lines total). The guide now covers:
1. Specification
2. Migration
3. Validation
4. Testing
5. Automation
6. Ergonomics
7. Implementation
8. Observability & Resilience
9. Hardening & Production Readiness
10. **Examples, Documentation, Quickstart**

---

## Next Steps

**Option A:** Compile Portions 1–10 into single master document:
```bash
cat docs/todo/{01..10}_*.md > docs/dsl_v2_refactor_plan.md
```

**Option B:** Generate PR body with all checklists and file paths:
```bash
python scripts/generate_pr_body.py docs/todo/ > .github/pull_request_template_dsl_v2.md
```

**Option C:** Begin implementation (start with Portion 3: schema + validators)

**Option D:** Create tracking issues for each portion (GitHub/JIRA)

---

**Ready to ship DSL v2! 🚀**
