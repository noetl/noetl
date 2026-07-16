"""NoETL Python API over the Rust CLI local executor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

from . import _native

__version__ = _native.version()


def run(
    playbook: str | Path,
    *,
    runtime: str = "auto",
    target: Optional[str] = None,
    variables: Optional[Mapping[str, str]] = None,
    json_output: bool = False,
    verbose: bool = False,
) -> dict:
    """Run a playbook through the Rust local executor and tool registry."""

    raw = _native.run(
        str(playbook),
        runtime,
        target,
        dict(variables or {}),
        json_output,
        verbose,
    )
    return json.loads(raw)


def registered_tools() -> list[str]:
    """Return the tool kinds compiled into this wheel."""

    return list(_native.registered_tools())


__all__ = ["__version__", "registered_tools", "run"]
