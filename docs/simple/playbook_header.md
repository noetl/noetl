# Playbook header and metadata

Define the playbook kind, version, and identity. Appears at the top of every file.

What it is
- Declares apiVersion and kind
- Provides metadata for identification and cataloging

Required keys
- apiVersion: noetl.io/v1
- kind: Playbook
- metadata.name: unique name within your catalog
- metadata.path: catalog path (used by tooling/tests)

Common optional keys
- metadata.version: your own semantic version (string)
- metadata.description: short human-readable summary

Example (structure only)
```
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: my_playbook
  path: examples/my_playbook
  version: "0.1.0"
  description: Minimal example
```

Rules and tips
- Keep `metadata.name` stable; it’s referenced in logs and tools.
- Use a consistent `metadata.path` reflecting repository location; tests may rely on it.
- Put large narrative docs in repository docs; keep header description concise.
