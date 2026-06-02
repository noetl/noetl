"""Pool routing for tool kinds — see noetl/ai-meta#42.

The Rust noetl-worker can dispatch most tool kinds via the shared
`noetl-tools` registry, but a handful are Python-runtime-bound and
can only run on the Python pool (the `agent` LLM-framework bridge
today; the `container` K8s-Job dispatcher per noetl/ai-meta#43 once
it switches to a callback shape; possibly others later).

This module is the source of truth for which kinds are Python-only.
Adding a new Python-only kind is a one-line entry in
:data:`POOL_FILTER_MAP`; no Rust-side change required because the
worker pools learn what they support by *which NATS consumer they
subscribe to*, not by querying a runtime contract.

The actual subject-routing logic ships in three phases per the
[noetl/ai-meta#42](https://github.com/noetl/ai-meta/issues/42)
plan; this module is the no-behaviour-change scaffold for PR-1.
:func:`route_subject` returns the legacy single subject until the
:envvar:`NOETL_COMMAND_ROUTING_ENABLED` env flag flips at cutover.
"""

from __future__ import annotations

import os
from typing import Optional

# Tool kinds that ONLY the Python worker pool can dispatch.  Default
# for anything not in this map: ``"shared"`` (both pools claim).
#
# Adding a new Python-only kind: one line here, plus the kind itself
# under ``noetl/tools/<kind>/``.  No Rust changes needed.
POOL_FILTER_MAP: dict[str, str] = {
    # `agent` — LLM agent framework bridge (ADK / LangChain / custom
    # callables) via dynamic Python module import.  Rust can't
    # replicate the ``importlib.import_module`` + ``getattr`` shape;
    # routes to Python pool only.
    "agent": "python",
}

# Default segment for kinds not in POOL_FILTER_MAP.  Both worker
# pools subscribe to the consumer bound to the ``shared`` subject
# branch, so today's "any pool claims any kind" behaviour is
# preserved for kinds with Rust parity.
DEFAULT_POOL_SEGMENT = "shared"

# Env-var gate.  Default off so PR-1 ships as a no-behaviour-change
# scaffold; :func:`route_subject` returns the legacy subject when the
# flag is off.  The cutover (PR-5) flips this to ``true`` after the
# consumer migration + worker-side env realignment land.  Accepted
# truthy values: ``"1"``, ``"true"``, ``"yes"`` (case-insensitive).
ROUTING_ENABLED_ENV = "NOETL_COMMAND_ROUTING_ENABLED"


def is_routing_enabled() -> bool:
    """Return ``True`` iff subject-segmented routing is enabled.

    See :data:`ROUTING_ENABLED_ENV` for the env-var contract.
    """
    return os.getenv(ROUTING_ENABLED_ENV, "").strip().lower() in {"1", "true", "yes"}


def pool_segment_for_kind(tool_kind: Optional[str]) -> str:
    """Return the pool segment (``"python"`` or ``"shared"``) for a tool kind.

    ``None`` / empty / unknown kinds map to :data:`DEFAULT_POOL_SEGMENT`
    so the routing is backward-compatible with commands that don't
    declare a tool kind (or declare one not yet in the map).
    """
    if not tool_kind:
        return DEFAULT_POOL_SEGMENT
    return POOL_FILTER_MAP.get(tool_kind, DEFAULT_POOL_SEGMENT)


def route_subject(
    base_subject: str,
    tool_kind: Optional[str],
    execution_id: int,
) -> str:
    """Derive the NATS subject for a command notification.

    When routing is disabled (default), returns ``base_subject``
    verbatim — no behaviour change vs. today's single-subject scheme.

    When enabled, returns the hierarchical subject::

        <base_subject>.<pool>.<execution_id>

    The ``execution_id`` suffix is for future NATS-level tracing (a
    consumer can subscribe to a single execution's commands without
    parsing payloads); workers ignore the trailing token because
    their consumer's ``filter_subject`` matches the ``<pool>``
    segment.
    """
    if not is_routing_enabled():
        return base_subject
    pool = pool_segment_for_kind(tool_kind)
    return f"{base_subject}.{pool}.{execution_id}"


__all__ = [
    "POOL_FILTER_MAP",
    "DEFAULT_POOL_SEGMENT",
    "ROUTING_ENABLED_ENV",
    "is_routing_enabled",
    "pool_segment_for_kind",
    "route_subject",
]
