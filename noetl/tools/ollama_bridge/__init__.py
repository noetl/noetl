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
ops/charts/noetl/templates/ollama-bridge-deployment.yaml when it lands).
"""

from .server import build_app  # re-exported for tests / programmatic use

__all__ = ["build_app"]
