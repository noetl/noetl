# Migration Guide: Loop → Iterator

We have standardized iteration on a single declarative iterator step:

New format
```
type: iterator
collection: "{{ <data_source> }}"
element: <element_variable>
# optional
mode: sequential | async            # default sequential
concurrency: <int>                  # when mode=async, default 8
enumerate: true | false             # default false (exposes {{ index }} when true)
where: "{{ <predicate on element> }}"   # filter items
limit: <int>                        # cap number of items
chunk: <int>                        # batch size; body executes per batch
order_by: "{{ <expression> }}"     # sort key expression
```

Legacy constructs (remove):
- `type: loop`
- `in:` (use `collection:`)
- `iterator:` (use `element:`)
- `mode: parallel` (use `mode: async`)
- `until:` (deprecated; use `where:` if a pure predicate)

Field mapping
- `type: loop` → `type: iterator`
- `in` → `collection`
- `iterator` → `element`
- `mode: parallel` → `mode: async`
- `until` → remove or translate to `where:` if it is a pure predicate

Binding rules
- Per-item variable is named by `element:` (e.g., `element: city` → `{{ city }}`)
- If `enumerate: true`, `{{ index }}` is available (0-based)
- Parent scope is readable via `{{ parent }}` inside iterator body
- Aggregated result shape under the iterator step result:
  ```yaml
  result:
    items: [ <per-item-or-batch-result> ]
    results: [ <alias of items> ]
    count: <int>
    errors: [ { index, message } ]
  ```

Guardrails
- Strings are never iterated character-by-character. If `collection` renders to a non-JSON string, it is treated as a single item.
- Iterating dicts requires intent; otherwise, transform your data upstream.

Before → After examples

Before
```yaml
type: loop
in: "{{ cities }}"
iterator: city
mode: parallel
task: { ... }
```

After
```yaml
type: iterator
collection: "{{ cities }}"
element: city
mode: async
task: { ... }
```

Until → Where (best-effort)
```yaml
type: loop
in: "{{ users }}"
iterator: u
until: "{{ u.status == 'done' }}"
run: [ ... ]
```

→

```yaml
type: iterator
collection: "{{ users }}"
element: u
where: "{{ u.status == 'done' }}"
run: [ ... ]
# Note: if `until` meant early termination, semantics differ vs filtering.
```

Nested
```yaml
- step: outer
  type: loop
  in: "{{ cities }}"
  iterator: city
  run:
    - step: inner
      type: loop
      in: "{{ city.districts }}"
      iterator: district
      task: { ... }
```

→

```yaml
- step: outer
  type: iterator
  collection: "{{ cities }}"
  element: city
  run:
    - step: inner
      type: iterator
      collection: "{{ city.districts }}"
      element: district
      task: { ... }
```

How to migrate
1) Run the codemod in dry-run mode to see planned changes:
   ```bash
   python3 scripts/migrate_loops_to_iterator.py --dry-run
   ```
2) Apply the codemod:
   ```bash
   python3 scripts/migrate_loops_to_iterator.py --apply
   ```
3) Validate playbooks:
   ```bash
   python3 scripts/validate_playbooks.py examples
   ```
4) Run the pipeline/tests in dry-run/mock mode and compare outputs.

