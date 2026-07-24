# NoETL

**NoETL** orchestrates APIs, databases, and scripts through a declarative
**Playbook DSL**. This package is the NoETL command-line tool, installable with
pip.

```bash
pip install noetl
```

It installs two equivalent commands, `noetl` and `ntl`, and an importable
Python API. There is no separate binary to download and nothing to put on your
`PATH` yourself.

```bash
noetl run pipeline.yaml --runtime local --set region=west
```

```python
import noetl

outcome = noetl.run("pipeline.yaml", variables={"region": "west"})
print(outcome["status"], outcome["final_result"])

noetl.cli(["catalog", "list"])   # any CLI subcommand
```

## What it is

The CLI is written in Rust and lives at
[noetl/cli](https://github.com/noetl/cli). This package compiles that crate
into a native extension module, so `noetl.run(...)` and the `noetl` command
both drive the same execution engine — nothing here reimplements playbook
execution or shells out to a separate process.

Every subcommand is available: `run`, `catalog`, `context`, `auth`, `register`,
`status`, `query`, `ehdb`, `provider`, `subscribe`, and the rest. Run
`noetl --help` for the full tree.

## Python API

| Function | Purpose |
|---|---|
| `noetl.run(playbook, **options)` | Execute a playbook locally; returns the run outcome as a dict. |
| `noetl.cli(args)` | Run any CLI subcommand; returns its exit code. |
| `noetl.__version__` | This package's version. |

`noetl.run()` returns the outcome envelope: `status`, `playbook_name`,
`playbook_path`, `started_at`, `completed_at`, `duration_seconds`,
`executed_steps`, `step_results`, `final_result`, and `error` when the run
failed. It executes locally; to submit to a distributed runtime, use
`noetl.cli(["run", playbook, "--runtime", "distributed"])`.

## Versioning

This package's version and the CLI's version are separate. `noetl --version`
reports the version of the Rust CLI compiled into this release — that is the
number to quote in a bug report against
[noetl/cli](https://github.com/noetl/cli/issues). `noetl.__version__` and
`pip show noetl` report the package version.

## Known limitation: DuckDB

These wheels are built **without** the embedded DuckDB engine. Compiling DuckDB
from its C++ source takes tens of minutes to an hour per platform, which a
five-platform wheel matrix cannot absorb.

Affected surfaces report a rebuild hint rather than running:

- `kind: duckdb` and `kind: ducklake` playbook steps
- the `sink: duckdb:` target
- the `noetl iap` command family, whose state ledger is a local `state.duckdb`

Everything else — HTTP, shell, Postgres, playbook composition, providers,
secrets, and the catalog/server/worker verbs — works normally. If you need
DuckDB, install the CLI from source with the feature enabled:

```bash
cargo install --bins noetl --features duckdb-integration
```

or use a [pre-built release binary](https://github.com/noetl/cli/releases),
Homebrew, or the APT package — all of which ship with DuckDB included.

## Requirements

Python 3.9 or newer. The wheels are `abi3`, so one wheel per platform serves
every supported Python version.

## Documentation

- [noetl.dev](https://noetl.dev) — user-facing documentation
- [CLI reference](https://github.com/noetl/cli/wiki)
- [Platform wiki](https://github.com/noetl/noetl/wiki)

## License

MIT
