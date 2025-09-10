# Query Conditions: Exact/Complete Match with OR

This page shows how to express an OR of exact (complete) matches in two common contexts you may use with NoETL:

- Shell (grep) when working with local files
- NoETL playbook conditions (Jinja "when" expressions)

---

## Shell: grep exact filename match for multiple alternatives

If you want to match ONLY specific filenames like:
- error_log.json
- event_log.json
- queue.json

Use an extended regex anchored to the start and end of the string. With a simple `ls -1` and `grep -E`:

```
ls -1 | grep -E '^(error_log\.json|event_log\.json|queue\.json)$'
```

Notes:
- `-E` enables extended regular expressions (alternation with `|`).
- `^` and `$` anchor the match to the full line (complete match, not partial).
- Dots are escaped: `\.`
- If your shell is zsh/bash, the quotes prevent the shell from interpreting regex metacharacters.

Alternative with ripgrep (rg):

```
ls -1 | rg -N '^(error_log\.json|event_log\.json|queue\.json)$'
```

Or using `find` (exact name match, multiple ORs):

```
find . -maxdepth 1 \(
  -name 'error_log.json' -o -name 'event_log.json' -o -name 'queue.json'
\) -print
```

---

## NoETL playbooks: exact-match OR in `when` conditions

In NoETL, `when` conditions are rendered with Jinja. For exact/complete match across multiple alternatives, prefer membership in a list instead of substring/regex, e.g.:

```yaml
- step: choose_file_branch
  next:
    - when: "{{ workload.filename in ['error_log.json', 'event_log.json', 'queue.json'] }}"
      then:
        - step: handle_known_file
    - else:
        - step: handle_other_file
```

Why this is preferred:
- `in ['a', 'b']` checks for exact equality to any element (i.e., OR of equals).
- Avoid using substring patterns like `"event|error|queue.json"` inside a Jinja condition — Jinja doesn’t treat that as a regex and substring checks can yield partial matches.

If you truly need regex, you can compare using Jinja’s `match`/`search` via a custom filter or by precomputing on the producing side. But in most cases, equality or membership is simpler and safer.

### Exact-match OR with multiple fields

You can combine equality and OR explicitly too:

```yaml
- when: "{{ workload.filename == 'error_log.json' or workload.filename == 'event_log.json' or workload.filename == 'queue.json' }}"
```

But the list membership form is shorter and clearer:

```yaml
- when: "{{ workload.filename in ['error_log.json', 'event_log.json', 'queue.json'] }}"
```

---

## Examples with logs in repo root

Given files in the project root:

```
error_log.json
event_log.json
queue.json
```

- Shell exact OR: `ls -1 | grep -E '^(error_log\.json|event_log\.json|queue\.json)$'`
- Playbook when: `{{ workload.filename in ['error_log.json','event_log.json','queue.json'] }}`

These will both ensure a complete match to exactly those three filenames.
