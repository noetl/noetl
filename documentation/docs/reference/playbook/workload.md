# Workload (inputs)

Top-level input values for a run. Treated as read-only during execution.

What it is
- A YAML mapping of scalars/lists/maps
- Available everywhere via `{{ workload.* }}`

Required keys
- None beyond `workload:` itself; structure is user-defined

Common patterns
- Static constants (e.g., base URLs, thresholds)
- Lists to iterate over (e.g., cities, users)
- Secrets by reference via header auth (use auth blocks; do not inline secrets here)

Rules and tips
- Reference with `{{ workload.key }}` and `{{ workload.list }}`
- For missing values, use defaults: `{{ workload.maybe | default('N/A') }}`
- Avoid huge blobs; prefer fetching data in steps (http, postgres, duckdb)
- Keep types consistent (e.g., numbers as numbers, not strings)

Examples (fragments)
- Static plus collection
```
  workload:
    message: "HTTP to PG demo"
    base_url: "https://api.open-meteo.com/v1"
    cities:
      - { name: London, lat: 51.51, lon: -0.13 }
      - { name: Paris,  lat: 48.85, lon:  2.35 }
      - { name: Berlin, lat: 52.52, lon: 13.41 }
```
- Cloud scope for storage
  workload:
    gcs_bucket: noetl-demo-19700101
