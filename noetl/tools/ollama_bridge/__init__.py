"""MCP-protocol bridge for local Ollama (Gemma, Qwen, Llama, ...).

This is a *server* — it speaks MCP JSON-RPC on the wire and translates
to Ollama's HTTP API at ``$OLLAMA_URL`` (default
``http://localhost:11434``). It is the cheap-first inference fabric
for self-troubleshoot playbooks: they call Ollama for a first-pass
analysis, then escalate to OpenAI / Claude only when local models
return low-confidence output.

The bridge is intentionally minimal — see ``server.py`` for the
complete surface. To run::

    python -m noetl.tools.ollama_bridge

or, in-cluster, deploy as a sidecar to noetl-worker (see
``catalog_template.yaml`` for the catalog manifest and
``docs/operations/ollama_bridge.md`` for the deployment runbook).

**Optional-dependency contract.** This package is opt-in. NoETL's
worker and server never import it for core functionality. Importing
``noetl.tools.ollama_bridge`` itself only pulls stdlib modules —
``aiohttp`` / ``fastapi`` / ``uvicorn`` are imported lazily inside
the functions that need them, so a deployment without those
packages can still load the module without a crash. Calling the
sidecar (via ``python -m noetl.tools.ollama_bridge``) is what
actually requires the optional deps; the noetl core has no such
requirement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING


__all__ = ["build_app"]


def __getattr__(name: str):
    """Lazy loader for the package's public surface.

    Defers the ``server.py`` import until something actually asks for
    ``build_app``. Importing ``noetl.tools.ollama_bridge`` therefore
    does *zero* work; importing ``build_app`` from it triggers the
    server module which is itself stdlib-only at module level
    (aiohttp / fastapi are lazy inside functions). This keeps the
    package safe to import from any noetl core path without pulling
    optional deps along for the ride.
    """
    if name == "build_app":
        from .server import build_app

        return build_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if TYPE_CHECKING:
    # Re-export for static analysers / IDE completion only — never runs
    # at import time.
    from .server import build_app  # noqa: F401
