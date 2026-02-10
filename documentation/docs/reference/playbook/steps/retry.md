# Retry in steps — Canonical v10

Canonical v10 removes step-level `retry:` blocks.

Retry belongs to **task policy** (`task.spec.policy.rules`) and is evaluated by the worker after a task produces its final `outcome`.

## See also
- Retry mechanism (canonical): `documentation/docs/reference/retry_mechanism_v2.md`
- Step spec: `documentation/docs/reference/dsl/step_spec.md`
