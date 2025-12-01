# Editor Snippets, Diagnostics, and Author Ergonomics

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Provide IDE integration, quick fixes, style guidelines, and authoring tools for DSL v2

---

## 6.1 VS Code User Snippets (YAML)

**File:** `.vscode/noetl.code-snippets`

```json
{
  "noetl step (simple)": {
    "prefix": "noetl-step",
    "body": [
      "- step: ${1:id}",
      "  desc: \"${2:describe step}\"",
      "  tool:",
      "    kind: ${3|http,postgres,python,duckdb,playbook,workbook|}",
      "    spec: { ${4:key}: ${5:value} }",
      "    args: { ${6:arg}: ${7:\"{{ value }}\"} }",
      "    result:",
      "      as: ${8:out}",
      "      sink:",
      "        - ${9|postgres,s3,file,duckdb|}: { ${10:key}: ${11:value} }",
      "  next:",
      "    - step: ${12:next_step}"
    ],
    "description": "NoETL v2: minimal step"
  },
  
  "noetl loop step": {
    "prefix": "noetl-loop",
    "body": [
      "- step: ${1:proc_items}",
      "  desc: \"Loop over items as 'item'\"",
      "  loop:",
      "    collection: \"${2:{{ workload.items }}}\"",
      "    element: ${3:item}",
      "    mode: ${4|sequential,parallel|}",
      "  tool:",
      "    kind: ${5|playbook,workbook,http,postgres,python,duckdb|}",
      "    spec: { ${6:key}: ${7:value} }",
      "    args: { ${8:arg}: ${9:\"{{ \"}${3}${10:\" }}\"} }",
      "    result:",
      "      pick: \"${11:{{ { 'id': item.id, 'val': this } }}}\"",
      "      as: ${12:last_item}",
      "      collect: { into: ${13:all_items}, mode: ${14|list,map|}${15:, key: \"{{ item.id }}\"} }",
      "      sink:",
      "        - ${16|postgres,s3,file,duckdb|}: { ${17:key}: ${18:value} }",
      "  next:",
      "    - step: ${19:after_loop}"
    ],
    "description": "NoETL v2: loop step with result handling"
  },
  
  "noetl join step (AND) with helpers": {
    "prefix": "noetl-join",
    "body": [
      "- step: ${1:join_acc}",
      "  desc: \"AND-join on predecessors\"",
      "  when: \"${2:{{ done('A') and ok('B') }}}\"",
      "  tool:",
      "    kind: python",
      "    spec:",
      "      code: |",
      "        def main(context, results):",
      "            return ${3:{}}",
      "    result: { as: ${4:joined} }",
      "  next:",
      "    - step: ${5:next_step}"
    ],
    "description": "NoETL v2: Petri-style AND-join with done()/ok()"
  },
  
  "noetl fanout step": {
    "prefix": "noetl-fanout",
    "body": [
      "- step: ${1:fanout}",
      "  desc: \"Fan-out to multiple targets\"",
      "  next:",
      "    - step: ${2:target_a}",
      "    - step: ${3:target_b}",
      "    - step: ${4:target_c}"
    ],
    "description": "NoETL v2: fan-out (routing-only step)"
  },
  
  "noetl http tool": {
    "prefix": "noetl-http",
    "body": [
      "tool:",
      "  kind: http",
      "  spec:",
      "    method: ${1|GET,POST,PUT,DELETE|}",
      "    endpoint: \"${2:{{ base_url }}/api/endpoint}\"",
      "    headers:",
      "      Authorization: \"${3:Bearer {{ token }}}\"",
      "    ${4:params: { ${5:key}: ${6:value} \\}}",
      "  args: { ${7:arg}: ${8:\"{{ value }}\"} }",
      "  result:",
      "    as: ${9:response}"
    ],
    "description": "NoETL v2: HTTP tool configuration"
  },
  
  "noetl postgres tool": {
    "prefix": "noetl-postgres",
    "body": [
      "tool:",
      "  kind: postgres",
      "  spec:",
      "    query: \"${1:SELECT * FROM table WHERE id = {{ user_id }}}\"",
      "    auth: ${2:{ credential: pg_cred \\}}",
      "  args: { ${3:arg}: ${4:\"{{ value }}\"} }",
      "  result:",
      "    as: ${5:query_result}"
    ],
    "description": "NoETL v2: Postgres tool configuration"
  },
  
  "noetl python tool": {
    "prefix": "noetl-python",
    "body": [
      "tool:",
      "  kind: python",
      "  spec:",
      "    code: |",
      "      def main(context, results):",
      "          ${1:# Your code here}",
      "          return ${2:{\\}}",
      "  result:",
      "    as: ${3:result}"
    ],
    "description": "NoETL v2: Python tool configuration"
  },
  
  "noetl playbook tool": {
    "prefix": "noetl-playbook",
    "body": [
      "tool:",
      "  kind: playbook",
      "  spec:",
      "    path: ${1:playbooks/my_playbook}",
      "    ${2:entry_step: ${3:start}}",
      "    ${4:return_step: ${5:done}}",
      "  args:",
      "    ${6:arg}: ${7:\"{{ value }}\"}",
      "  result:",
      "    as: ${8:playbook_result}"
    ],
    "description": "NoETL v2: Playbook tool configuration"
  },
  
  "noetl conditional next": {
    "prefix": "noetl-next-cond",
    "body": [
      "next:",
      "  - when: \"${1:{{ score > 0.8 }}}\"",
      "    step: ${2:high}",
      "  - when: \"${3:{{ score > 0.5 }}}\"",
      "    step: ${4:medium}",
      "  - step: ${5:low}  # Else"
    ],
    "description": "NoETL v2: conditional next (if/elif/else)"
  },
  
  "noetl result sink multi": {
    "prefix": "noetl-sink-multi",
    "body": [
      "result:",
      "  as: ${1:data}",
      "  sink:",
      "    - postgres:",
      "        table: ${2:public.results}",
      "        mode: upsert",
      "        key: id",
      "        args:",
      "          id: \"${3:{{ out.id }}}\"",
      "    - s3:",
      "        bucket: ${4:data-lake}",
      "        key: \"${5:results/{{ execution_id }}.json}\"",
      "    - file:",
      "        path: \"${6:/tmp/result.json}\""
    ],
    "description": "NoETL v2: multi-sink fan-out"
  },
  
  "noetl bind context": {
    "prefix": "noetl-bind",
    "body": [
      "bind:",
      "  ${1:key}: ${2:\"{{ workload.value }}\"}"
    ],
    "description": "NoETL v2: bind extra context"
  },
  
  "noetl loop until": {
    "prefix": "noetl-loop-until",
    "body": [
      "loop:",
      "  collection: \"${1:{{ items }}}\"",
      "  element: ${2:item}",
      "  mode: ${3|sequential,parallel|}",
      "  until: \"${4:{{ condition }}}\""
    ],
    "description": "NoETL v2: loop with early exit condition"
  }
}
```

---

### Installation

**VS Code:**
1. Press `Cmd+Shift+P` (Mac) or `Ctrl+Shift+P` (Windows/Linux)
2. Type "Preferences: Configure User Snippets"
3. Select "New Global Snippets file" or "noetl" workspace
4. Paste the JSON above

**Usage:**
- In YAML file, type `noetl-` to see all snippets
- Type specific prefix (e.g., `noetl-step`) and press `Tab`
- Navigate placeholders with `Tab`
- Multi-choice placeholders use arrow keys

---

### Tip

If your repo has multiple languages, scope to YAML only by placing snippets under `yaml.json` and copying entries, or add `"scope": "yaml"` to each snippet.

---

## 6.2 Quick Diagnostics (Author-Facing)

**Add to `docs/dsl_errors.md` or display in validation output:**

---

### E001 — "Unknown top-level key(s)"

**Why:** Only `step, desc, when, bind, loop, tool, next` allowed at step level.

**Fix:** Move plugin configuration to `tool.spec`; delete legacy `args`/`save` at step level.

**Example:**
```yaml
# ❌ Before
- step: fetch
  method: GET        # Wrong level
  endpoint: "/api"   # Wrong level
  args: {}          # Wrong level

# ✅ After
- step: fetch
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "/api"
    args: {}
```

---

### E002 — "tool: iterator is invalid"

**Why:** Iteration is step-level (`loop`), not a tool type.

**Fix:** Create `loop` block with `collection`/`element`; remove `tool: iterator`.

**Example:**
```yaml
# ❌ Before
- step: proc
  tool: iterator
  collection: "{{ items }}"
  element: item

# ✅ After
- step: proc
  loop:
    collection: "{{ items }}"
    element: item
  tool:
    kind: <actual_plugin>
    spec: {}
```

---

### E003 — "result.sink must be a list of single-key objects"

**Why:** Sinks are fan-out destinations; each must be keyed by sink type.

**Fix:** Wrap in array and key by sink ID.

**Example:**
```yaml
# ❌ Before
result:
  sink:
    postgres: { table: t }  # Object, not list

# ✅ After
result:
  sink:
    - postgres:
        table: t
        key: id
        args:
          id: "{{ out.id }}"
```

---

### E004 — "Multiple next elses" or "More than one edge without 'when'"

**Why:** Only one `next` item may omit `when` (else-fallthrough).

**Fix:** Add `when` conditions to all but the final edge.

**Example:**
```yaml
# ❌ Before
next:
  - step: A     # else 1
  - step: B     # else 2 (ERROR)

# ✅ After
next:
  - when: "{{ condition }}"
    step: A
  - step: B     # Only one else
```

---

### E005 — "Reserved namespace 'step'"

**Why:** `step.*` namespace is reserved for engine status tracking.

**Fix:** Don't write `bind.step` or `result.as: step`. Use helpers to read status.

**Example:**
```yaml
# ❌ Before
bind:
  step: value        # Reserved

result:
  as: step          # Reserved

# ✅ After
bind:
  step_data: value

result:
  as: step_result

# Read status with helpers
when: "{{ done('step_id') }}"
```

---

### E006 — "Missing tool.spec required fields for kind=X"

**Why:** Each plugin type has required fields in `spec`.

**Fix:** Fill per-kind contract.

**Required fields by plugin:**

| Plugin | Required Fields |
|--------|----------------|
| `playbook` | `path` |
| `workbook` | `name` |
| `http` | `method`, `endpoint` |
| `postgres` | `query` |
| `python` | `code` OR (`module` + `callable`) |
| `duckdb` | `query` |

**Example:**
```yaml
# ❌ Before
tool:
  kind: playbook
  spec: {}  # Missing path

# ✅ After
tool:
  kind: playbook
  spec:
    path: playbooks/my_playbook
```

---

### E007 — "Loop missing collection/element"

**Why:** Both are required for iteration.

**Fix:** Provide both fields in `loop`.

**Example:**
```yaml
# ❌ Before
loop:
  collection: "{{ items }}"
  # Missing element

# ✅ After
loop:
  collection: "{{ items }}"
  element: item
```

---

### E008 — "collect.mode: map requires key"

**Why:** Map collection needs key expression for indexing.

**Fix:** Add `key` field to `collect`.

**Example:**
```yaml
# ❌ Before
collect:
  into: user_map
  mode: map  # Missing key

# ✅ After
collect:
  into: user_map
  mode: map
  key: "{{ out.user_id }}"
```

---

## 6.3 In-Editor Quick Fixes (Regex Tasks)

**File:** `.vscode/tasks.json` (add to existing tasks)

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "fix:next-scalar",
      "type": "shell",
      "command": "fd -e yaml | xargs sd '(^\\s*next:\\s*)([A-Za-z0-9_\\-.]+)\\s*$' '$1\\n  - step: $2'",
      "problemMatcher": [],
      "presentation": {
        "echo": true,
        "reveal": "always",
        "panel": "shared"
      },
      "group": "none"
    },
    {
      "label": "fix:iter-alias",
      "type": "shell",
      "command": "fd -e yaml | xargs sd '^(\\s*)(iter|iterator|over|coll):(\\s*)$' '$1loop:$3'",
      "problemMatcher": [],
      "presentation": {
        "echo": true,
        "reveal": "always",
        "panel": "shared"
      },
      "group": "none"
    },
    {
      "label": "fix:save->sink",
      "type": "shell",
      "command": "fd -e yaml | xargs sd '\\n\\s+sink:\\s*\\n' '\\n  tool:\\n    result:\\n      sink:\\n        - postgres:\\n'",
      "problemMatcher": [],
      "presentation": {
        "echo": true,
        "reveal": "always",
        "panel": "shared"
      },
      "group": "none"
    },
    {
      "label": "fix:all-quick",
      "dependsOn": ["fix:next-scalar", "fix:iter-alias", "fix:save->sink"],
      "problemMatcher": []
    }
  ]
}
```

**Requirements:**
- [`fd`](https://github.com/sharkdp/fd) - Fast file finder
- [`sd`](https://github.com/chmln/sd) - Intuitive find & replace

**Install:**
```bash
# macOS
brew install fd sd

# Ubuntu/Debian
apt install fd-find
cargo install sd

# Windows
scoop install fd sd
```

**Usage:**
1. `Tasks: Run Task → fix:next-scalar` - Convert scalar next to array
2. `Tasks: Run Task → fix:iter-alias` - Rename iteration aliases to loop
3. `Tasks: Run Task → fix:save->sink` - Convert save to result.sink
4. `Tasks: Run Task → fix:all-quick` - Run all fixes

**Note:** Prefer AST-based codemod for accuracy; keep these for quick triage.

---

## 6.4 Authoring Ergonomics (Style Guide)

### Step IDs

**Format:** `snake_case` or `kebab-case`

**Guidelines:**
- Keep stable and greppable
- Descriptive but concise
- No special characters except `_` and `-`

**Examples:**
```yaml
✅ Good: fetch_user, score_user, join_acc, load_data, transform_records
❌ Bad: s1, temp, x, DoSomething, fetch-user-and-score
```

---

### Result Names (`result.as`)

**Format:** Nouns, scoped

**Guidelines:**
- Avoid generic names like `result`, `data`, `output`
- Use domain-specific names
- Add scope when needed: `raw`, `processed`, `summary`

**Examples:**
```yaml
✅ Good: user_raw, user_score, last_score, summary, profiles_list
❌ Bad: result, data, out, res, temp
```

---

### Collect Keys

**Lists:** Plural nouns

**Maps:** Descriptive collection name + key expression

**Examples:**
```yaml
# List collection
collect:
  into: all_scores      # ✅ Plural noun
  mode: list

collect:
  into: users           # ✅ Plural noun
  mode: list

# Map collection
collect:
  into: users_by_id     # ✅ Descriptive
  mode: map
  key: "{{ out.user_id }}"

collect:
  into: score_map       # ✅ Clear purpose
  mode: map
  key: "{{ out.id }}"
```

---

### Loop Element Naming

**Rule:** Singular of collection name

**Examples:**
```yaml
# ✅ Good
loop:
  collection: "{{ workload.users }}"
  element: user

loop:
  collection: "{{ rows }}"
  element: row

loop:
  collection: "{{ items }}"
  element: item

# ❌ Bad
loop:
  collection: "{{ workload.users }}"
  element: u  # Too short

loop:
  collection: "{{ items }}"
  element: items  # Not singular
```

---

### Edge Guards

**Prefer helpers:** Use engine status functions

**Examples:**
```yaml
# ✅ Good: Use helpers
when: "{{ done('fetch_user') and ok('score_user') }}"
when: "{{ loop_done('proc_users') }}"
when: "{{ all_done(['step_a', 'step_b', 'step_c']) }}"
when: "{{ any_done(['alt_a', 'alt_b']) }}"

# ⚠️ Acceptable: Direct status access
when: "{{ step.fetch_user.status.done }}"

# ❌ Bad: Manual status checks
when: "{{ context.step.fetch_user.status.done == true }}"
```

**Else Edge:**
- Always last in `next` array
- No `when` condition

```yaml
next:
  - when: "{{ score > 80 }}"
    step: high
  - when: "{{ score > 50 }}"
    step: medium
  - step: low  # ✅ Else (no when)
```

---

### Tool.Spec

**Rule:** Only plugin contract (static configuration)

**Keep dynamic per-execution inputs in `tool.args`**

**Examples:**
```yaml
# ✅ Good: Static in spec, dynamic in args
tool:
  kind: http
  spec:
    method: GET          # Static
    endpoint: "/api/users"  # Static template
  args:
    user_id: "{{ workload.user_id }}"  # Dynamic

# ❌ Bad: Everything in spec
tool:
  kind: http
  spec:
    method: GET
    endpoint: "/api/users"
    user_id: "{{ workload.user_id }}"  # Should be in args
```

---

### Sinks

**Prefer idempotent sinks for parallel loops**

Use `mode: upsert` with unique `key` to avoid duplicates.

**Examples:**
```yaml
# ✅ Good: Idempotent upsert
loop:
  mode: parallel
tool:
  result:
    sink:
      - postgres:
          table: results
          mode: upsert     # Idempotent
          key: id
          args:
            id: "{{ execution_id }}:{{ item.id }}"

# ⚠️ Risky: Insert in parallel
loop:
  mode: parallel
tool:
  result:
    sink:
      - postgres:
          table: results
          mode: insert    # May create duplicates
```

---

## 6.5 "Skeletons" for Common Tools

### HTTP GET → File + Postgres

```yaml
- step: get_prof
  desc: "Fetch profile from API and store"
  tool:
    kind: http
    spec:
      method: GET
      endpoint: "{{ base }}/users/{{ workload.user_id }}"
      headers:
        Authorization: "{{ secrets.api_token }}"
    result:
      as: prof
      sink:
        - file:
            path: "/tmp/user_{{ workload.user_id }}.json"
        - postgres:
            table: public.api_profiles
            mode: upsert
            key: id
            args:
              id: "{{ prof.id }}"
              payload: "{{ prof }}"
```

---

### Postgres → DuckDB

```yaml
- step: load_users
  desc: "Load users from Postgres into DuckDB"
  tool:
    kind: postgres
    spec:
      query: "SELECT id, name, email FROM public.users"
      auth: "{{ workload.pg_auth }}"
    result:
      as: users
      sink:
        - duckdb:
            file: "./stage.duckdb"
            table: users
```

---

### Playbook Fan-Out + Collect

```yaml
- step: proc_users
  desc: "Process each user with sub-playbook"
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
            mode: upsert
            key: id
            args:
              id: "{{ execution_id }}:{{ out.name }}"
              score: "{{ out.score }}"
  next:
    - step: summarize
```

---

### Python Transform + Multi-Sink

```yaml
- step: transform_data
  desc: "Transform data with Python and fan-out"
  tool:
    kind: python
    spec:
      code: |
        def main(context, results):
            raw = context["raw_data"]
            return {
                "id": raw["id"],
                "processed_at": datetime.now().isoformat(),
                "value": raw["value"] * 2
            }
    result:
      as: processed
      sink:
        - postgres:
            table: processed_data
            mode: upsert
            key: id
            args:
              id: "{{ processed.id }}"
              value: "{{ processed.value }}"
              processed_at: "{{ processed.processed_at }}"
        - s3:
            bucket: data-lake
            key: "processed/{{ execution_id }}/{{ processed.id }}.json"
```

---

### DuckDB Query with File Sink

```yaml
- step: query_parquet
  desc: "Query parquet with DuckDB"
  tool:
    kind: duckdb
    spec:
      query: |
        SELECT user_id, COUNT(*) as event_count
        FROM read_parquet('{{ workload.parquet_path }}')
        GROUP BY user_id
      file: "./analytics.duckdb"
    result:
      as: user_events
      sink:
        - file:
            path: "/tmp/user_events_{{ execution_id }}.json"
```

---

### Workbook Call with Guard

```yaml
- step: summarize
  desc: "Summarize scores (wait for loop)"
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

---

## 6.6 "Author Checklist"

**Paste near examples or in PR template:**

```markdown
### DSL v2 Author Checklist

- [ ] Only 4-char step keys used (`step, desc, when, bind, loop, tool, next`)
- [ ] If looping: both `collection` and `element` set
- [ ] `tool.kind` + `tool.spec` present; dynamic inputs in `tool.args`
- [ ] Result handling uses `result.as` (if needed) and `result.sink` (list)
- [ ] Branching uses ordered `next` with at most one else (no `when`)
- [ ] AND-joins use helpers: `done()/ok()/loop_done()`
- [ ] No writes to `step.*` namespace
- [ ] Step IDs are descriptive and stable (snake_case or kebab-case)
- [ ] Result names avoid generic terms (`result`, `data`, `output`)
- [ ] Loop element naming is singular of collection
- [ ] Parallel loops use idempotent sinks (upsert with key)
- [ ] Ran validation: `make dsl.validate` ✅
- [ ] Ran lint: `make dsl.lint` ✅
```

---

## 6.7 Copilot/Codex Prompt

**Paste this prompt when refactoring workflows in VS Code with Copilot:**

```markdown
You are refactoring NoETL workflows to DSL v2.

**Rules:**
- Step keys exactly: `step, desc, when, bind, loop, tool, next`
- Move step-level `args`/`save` into `tool.args` / `tool.result.sink` (list)
- Replace `tool: iterator` and `iter`/`iterator`/`over`/`coll` with `loop {collection, element, mode?, until?}`
- Flatten nested `task:` blocks into `tool {kind, spec, args, result}`
- `next` must be a list of `{step, when?}`, last item may omit `when`
- Use helpers in guards: `done('A')`, `ok('B')`, `loop_done('C')`

**Per-Kind Spec Requirements:**
- `playbook`: `spec.path` (required), `spec.entry_step` (optional), `spec.return_step` (optional)
- `workbook`: `spec.name` (required)
- `http`: `spec.method`, `spec.endpoint` (required), `spec.headers`, `spec.params` (optional)
- `postgres`: `spec.query` (required), `spec.auth`, `spec.params` (optional)
- `python`: `spec.code` OR (`spec.module` + `spec.callable`)
- `duckdb`: `spec.query` (required), `spec.file` (optional)

**Tasks:**
1. Update current file to DSL v2
2. Ensure per-kind spec is correct
3. Add `result.as` names when downstream uses the value
4. Add `result.collect` when loop results are consumed later
5. Convert guards to use helpers where appropriate
6. Run quick validation against JSON Schema (assume `validate_dsl_v2.py` exists)

**Output only the updated YAML.**
```

---

## 6.8 Optional: VS Code Problem Matchers

**File:** `.vscode/settings.json` (add to existing settings)

```json
{
  "problemMatcher": {
    "owner": "noetl-dsl",
    "fileLocation": ["relative", "${workspaceFolder}"],
    "pattern": [
      {
        "regexp": "^(FAIL|ERR)\\s+(.*?):\\s+(.*)$",
        "severity": 2,
        "file": 2,
        "message": 3
      },
      {
        "regexp": "^\\s+-\\s+(.*)$",
        "severity": 2,
        "message": 1
      }
    ]
  }
}
```

**Bind to `dsl:lint` task for inline gutter errors:**

```json
{
  "tasks": [
    {
      "label": "dsl:lint",
      "type": "shell",
      "command": "python scripts/lint_dsl_v2.py ${file}",
      "problemMatcher": "$noetl-dsl",
      "presentation": {
        "reveal": "always",
        "panel": "dedicated"
      }
    }
  ]
}
```

**Usage:**
- Run task on current file
- Errors appear in Problems panel
- Click to navigate to issue

---

## 6.9 Micro "Lint Rules of Thumb"

**For docs sidebar or quick reference:**

---

### 1. One Executable Per Step

**Rule:** Each step has at most one `tool` or is routing-only (fan-out).

**Rationale:** Steps are atomic units of work. Composition via `next`, not nesting.

```yaml
# ✅ Good: One tool
- step: fetch
  tool: { kind: http, ... }

# ✅ Good: Routing only
- step: fanout
  next:
    - step: A
    - step: B

# ❌ Bad: Multiple tools
- step: fetch_and_transform
  tool: { kind: http, ... }
  tool: { kind: python, ... }  # ERROR: Can't have two tools
```

---

### 2. Guard Reducers

**Rule:** Don't jump straight into a reducer—guard it with `when`.

**Rationale:** Reducers consume aggregated results; must wait for all inputs.

```yaml
# ✅ Good: Guarded reducer
- step: summarize
  when: "{{ all_done(['proc_a', 'proc_b', 'proc_c']) }}"
  tool: { kind: workbook, spec: { name: summarize } }

# ❌ Bad: Unguarded reducer
- step: summarize
  tool: { kind: workbook, spec: { name: summarize } }
  # May execute before inputs ready
```

---

### 3. Explicit Keys for Upserts in Loops

**Rule:** In parallel loops, use explicit unique `key` for upserts.

**Rationale:** Prevents duplicate inserts from concurrent workers.

```yaml
# ✅ Good: Explicit unique key
loop:
  mode: parallel
tool:
  result:
    sink:
      - postgres:
          mode: upsert
          key: id
          args:
            id: "{{ execution_id }}:{{ item.id }}"  # Unique

# ❌ Bad: Auto-generated key (may collide)
loop:
  mode: parallel
tool:
  result:
    sink:
      - postgres:
          mode: insert  # No deduplication
```

---

### 4. Static in Spec, Runtime in Args

**Rule:** Keep static configuration in `spec`, runtime values in `args`.

**Rationale:** Clear separation of concerns; spec is plugin contract, args are inputs.

```yaml
# ✅ Good: Clear separation
tool:
  kind: http
  spec:
    method: GET           # Static
    endpoint: "/api/users"  # Static template
  args:
    user_id: "{{ workload.user_id }}"  # Runtime

# ❌ Bad: Mixed concerns
tool:
  kind: http
  spec:
    method: GET
    endpoint: "/api/users"
    user_id: "{{ workload.user_id }}"  # Should be in args
```

---

### 5. Deterministic Next Evaluation

**Rule:** Keep `next` deterministic; evaluate in order; include final else when branches aren't exhaustive.

**Rationale:** Predictable flow; avoid dead-end steps.

```yaml
# ✅ Good: Exhaustive with else
next:
  - when: "{{ score > 80 }}"
    step: high
  - when: "{{ score > 50 }}"
    step: medium
  - step: low  # Else (catches all remaining)

# ⚠️ Risky: Non-exhaustive (step may hang if score <= 50)
next:
  - when: "{{ score > 80 }}"
    step: high
  # Missing else!
```

---

### 6. Avoid Generic Context Names

**Rule:** Use descriptive, scoped names for `result.as`.

**Rationale:** Prevents namespace collisions and improves readability.

```yaml
# ✅ Good: Descriptive names
result:
  as: user_raw
result:
  as: user_score
result:
  as: profiles_summary

# ❌ Bad: Generic names
result:
  as: result
result:
  as: data
result:
  as: temp
```

---

### 7. Singular Element Names

**Rule:** Loop `element` should be singular of `collection` name.

**Rationale:** Natural language mapping; improves template readability.

```yaml
# ✅ Good: Singular element
loop:
  collection: "{{ workload.users }}"
  element: user  # Singular

# ❌ Bad: Plural element
loop:
  collection: "{{ workload.users }}"
  element: users  # Should be singular
```

---

### 8. Prefer Helpers Over Raw Status

**Rule:** Use engine helpers (`done()`, `ok()`) instead of raw status access.

**Rationale:** Cleaner syntax; abstraction layer for future changes.

```yaml
# ✅ Good: Use helpers
when: "{{ done('fetch') and ok('transform') }}"

# ⚠️ Acceptable: Direct status
when: "{{ step.fetch.status.done and step.transform.status.ok }}"

# ❌ Bad: Verbose manual checks
when: "{{ context.step.fetch.status.done == true and context.step.transform.status.ok == true }}"
```

---

## 6.10 Editor Integration Summary

### Quick Start

1. **Install snippets:** `.vscode/noetl.code-snippets`
2. **Add tasks:** `.vscode/tasks.json` (quick fixes)
3. **Configure problem matcher:** `.vscode/settings.json`
4. **Use Copilot prompt:** When refactoring workflows

### Common Workflows

**Create new step:**
1. Type `noetl-step` → Tab
2. Fill placeholders
3. Run `make dsl.validate`

**Create loop:**
1. Type `noetl-loop` → Tab
2. Fill placeholders
3. Run `make dsl.lint`

**Fix legacy construct:**
1. Run `Tasks: Run Task → fix:all-quick`
2. Review changes
3. Run `make dsl.validate`

**Refactor with Copilot:**
1. Select workflow YAML
2. Open Copilot Chat
3. Paste refactor prompt
4. Review and apply suggestions

---

## Next Steps

This document provides **editor integration and authoring ergonomics**. Recommended actions:

1. Install VS Code snippets
2. Add quick-fix tasks
3. Configure problem matchers
4. Share style guide with team
5. Test Copilot prompt on sample workflows

---

**Ready for implementation or next documentation portion.**
