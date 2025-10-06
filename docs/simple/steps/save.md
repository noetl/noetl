# Save block

For a more detailed usage example check: `tests/fixtures/playbooks/http_duckdb_postgres/http_duckdb_postgres.yaml`

Persist step outputs to named variables or storages.

Inline per-step save:
```YAML
- step: get
  type: http
  url: https://example.com
  save: { name: page, data: "{{ this.data }}" }
```

Iterator aggregated save:
```YAML
- step: http_loop
  type: iterator
  ...
  save:
    - name: http_loop
      data: "{{ this.result }}"
```

Notes:
- `name` is the variable to store under; `data` is an expression.
- Inside iterator inner steps, `this.data` is the current step output.
- On the iterator itself, `this.result` is the list of per-item outputs.
