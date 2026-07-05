# NoETL

**NoETL** is an automation framework for orchestrating **APIs, databases, and scripts** using a declarative **Playbook DSL**.

Execution is standardized around an **MCP-style tool model**: consistent tool contracts, structured input/output, and a predictable lifecycle. From an MCP perspective, `tools` include API endpoints, database operations, and scripts/utilities **NoETL** orchestrates and optimizes them via playbooks.

With **NoETL Gateway**, playbooks can be deployed as a **distributed backend**: developers ship business logic as playbooks, and UIs/clients call stable endpoints without deploying dedicated microservices for each workflow.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)

## Documentation

**https://noetl.dev** — user-facing site.

**[NoETL wiki](https://github.com/noetl/noetl/wiki)** — operator and
developer reference. Pages mirror the code tree under `noetl/noetl`.

Async batch acceptance and recovery references (on the wiki):

- [Batch Events API](https://github.com/noetl/noetl/wiki/batch_events_async) — `POST /api/events/batch` async acceptance flow
- [Recovery: Auto-Resume](https://github.com/noetl/noetl/wiki/recovery_autoresume) — readiness-gated parent-execution restart at startup
- [Command Reaper](https://github.com/noetl/noetl/wiki/command_reaper) — runtime re-publish for orphaned / stranded commands

### Distributed runtime components

Reference docs for the event-sourced, projection-backed runtime
(implements v2 distributed-runtime spec phases 0–2; spec lives in
`noetl/docs` at [`docs/features/noetl_distributed_runtime_spec.md`](https://github.com/noetl/docs/blob/main/docs/features/noetl_distributed_runtime_spec.md)):

- **[Event Store](https://github.com/noetl/noetl/wiki/event_store)** —
  durable append-only event log (port + Postgres adapter), `EventRecord`
  envelope, optimistic concurrency via `expected_version`.
- **[Projection Store](https://github.com/noetl/noetl/wiki/projection_store)**
  — version-monotonic projection + snapshot store (port + Postgres
  adapter), query interface for replay state.
- **[Outbox](https://github.com/noetl/noetl/wiki/outbox)** — transactional
  outbox publisher (`python -m noetl.outbox`) that drains `noetl.outbox`
  to NATS with at-least-once retry/backoff.
- **[Projector](https://github.com/noetl/noetl/wiki/projector)** —
  out-of-process projection worker (`python -m noetl.projector`),
  durable NATS pull consumer, shard-stable, Prometheus metrics,
  replay-state folding shared with the in-process replay API.

### EHDB Integration

**The EHDB (Event Horizon Database) integration is Rust-only.** It lives in
the Rust worker ([`noetl/worker`](https://github.com/noetl/worker),
`src/ehdb`), which calls the `ehdb-reference` crate **in process** — readiness,
bounded data-plane append/read, and event-stream project/consume/ack — with no
subprocess and no parallel Python implementation. Because production runs the
Rust worker, that is the only EHDB path that executes.

The former Python EHDB modules (`noetl.core.ehdb_*`), their worker bootstrap
wiring, step CLIs, and the bundled `ehdb-local-reference` helper binary were
**retired** in favour of the Rust integration (see
[noetl/ehdb#234](https://github.com/noetl/ehdb/issues/234)). EHDB stays
disabled by default and control-plane-only for gateway/api/server; the
`NOETL_EHDB_*` env contract is rendered by the ops Helm charts and consumed by
the Rust worker.

## Repository model (ai-meta driven)

NoETL development is now coordinated through the `ai-meta` repository:

- Orchestration/meta: https://github.com/noetl/ai-meta
- Server: https://github.com/noetl/server
- Worker: https://github.com/noetl/worker
- Gateway: https://github.com/noetl/gateway
- CLI: https://github.com/noetl/cli
- Tools: https://github.com/noetl/tools
- End-to-end fixtures: https://github.com/noetl/e2e
- Ops/automation: https://github.com/noetl/ops
- Docs: https://github.com/noetl/docs

`ai-meta` tracks all component repositories as Git submodules and is the primary place to
coordinate cross-repo changes, pointer bumps, and release choreography.

End-to-end integration playbooks, fixture payloads, local credential templates, notebooks,
and Gateway UI test fixtures live in `noetl/e2e`.

## Distribution channels

- **PyPI**
  - `noetl` (Python): https://pypi.org/project/noetl/
- **Rust components**
  - CLI repo: https://github.com/noetl/cli
  - Gateway repo: https://github.com/noetl/gateway
  - Server repo: https://github.com/noetl/server
  - Worker repo: https://github.com/noetl/worker
  - Tools repo: https://github.com/noetl/tools
- **APT (Debian/Ubuntu)**
  - Repo: https://github.com/noetl/apt
- **Homebrew**
  - Tap: https://github.com/noetl/homebrew-tap

## License

Dual License — see [LICENSE](LICENSE) for details.
