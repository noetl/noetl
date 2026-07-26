"""NoETL — the workflow automation CLI, importable from Python.

This package *is* the NoETL CLI. The `noetl` command it installs and the
functions below both call into the same Rust code the standalone binary runs:
the clap command tree for :func:`cli` and the local execution engine for
:func:`run`. Nothing here reimplements playbook execution.

Typical use::

    import noetl

    outcome = noetl.run("pipeline.yaml", variables={"region": "west"})
    print(outcome["status"], outcome["final_result"])

    noetl.cli(["catalog", "list"])   # any CLI subcommand
"""

from __future__ import annotations

import json
import sys
from os import PathLike
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import _native

__version__: str = _native.__version__

__all__ = ["run", "cli", "main", "__version__"]


def run(
    playbook: str | PathLike[str],
    *,
    runtime: str = "local",
    variables: Mapping[str, Any] | None = None,
    target: str | None = None,
    verbose: bool = False,
    quiet: bool = True,
    facts_out: str | PathLike[str] | None = None,
    merge: bool = False,
) -> dict[str, Any]:
    """Execute a playbook and return its outcome.

    Args:
        playbook: Path to a playbook YAML file.
        runtime: Only ``"local"`` is supported here — the distributed runtime
            submits to a server and reports progress rather than returning an
            outcome, so drive it with :func:`cli` instead.
        variables: Workload values, equivalent to repeated ``--set k=v``. Values
            are stringified, matching the CLI.
        target: Entry step, equivalent to ``--target``.
        verbose: Emit step-by-step detail to stderr.
        quiet: Suppress the engine's progress output. Defaults to ``True``
            because the outcome comes back as a value here; pass ``False`` to
            watch a long run.
        facts_out: Append emitted provider facts to this JSONL file.
        merge: Merge mode, equivalent to the CLI's merge flag.

    Returns:
        The run outcome: ``status``, ``playbook_name``, ``playbook_path``,
        ``started_at``, ``completed_at``, ``duration_seconds``,
        ``executed_steps``, ``step_results``, ``final_result``, and ``error``
        when the run failed.

    Raises:
        ValueError: The playbook does not exist, or an unsupported runtime.
        RuntimeError: The run itself failed.
    """
    if runtime != "local":
        raise ValueError(
            f"noetl.run() executes locally; runtime={runtime!r} is not available here. "
            f'Use noetl.cli(["run", <playbook>, "--runtime", {runtime!r}]) instead.'
        )

    normalised = {str(key): _stringify(value) for key, value in (variables or {}).items()}

    outcome = _native.run_playbook(
        str(playbook),
        variables=normalised,
        target=target,
        verbose=verbose,
        quiet=quiet,
        facts_out=None if facts_out is None else str(facts_out),
        merge=merge,
    )
    return json.loads(outcome)


def _stringify(value: Any) -> str:
    """Match the CLI's ``--set`` coercion: JSON scalars unquoted, rest as JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value)


def cli(args: Sequence[str] | None = None) -> int:
    """Run any CLI subcommand and return its exit code.

    This is the full command tree — ``run``, ``catalog``, ``context``, ``auth``,
    ``ehdb`` and the rest — with output going to this process's stdout and
    stderr, exactly as the ``noetl`` command produces it.

    Args:
        args: Arguments *without* the program name, e.g. ``["catalog", "list"]``.
            Defaults to this process's own arguments.
    """
    if args is None:
        # Console script: pass our own argv through, so `ntl --help` is
        # self-titled `ntl` exactly as the native binary is.
        argv = [Path(sys.argv[0]).stem or "noetl", *sys.argv[1:]]
    else:
        argv = ["noetl", *(str(arg) for arg in args)]
    return _native.cli_main(argv)


def main() -> int:
    """Console-script entry point for the ``noetl`` command."""
    return cli()
