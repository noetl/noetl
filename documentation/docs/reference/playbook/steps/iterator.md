# Loops/iteration in steps — Canonical v10

Canonical v10 expresses iteration as a **step modifier**, not a step type:

- `step.loop` defines fan-out (`in` + `iterator` + `loop.spec`)
- iteration-local state lives under `iter.*`
- streaming/pagination uses task policy (`do: jump` / `do: break`)

## See also
- Loop iteration guide: `documentation/docs/reference/iterator_v3.md`
- Pagination pattern: `documentation/docs/reference/pagination_v2.md`
- Step spec: `documentation/docs/reference/dsl/noetl_step_spec.md`
