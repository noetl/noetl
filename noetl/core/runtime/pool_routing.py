"""Pool routing for tool kinds and privileged playbook paths.

Two routing keys, applied in order:

1. **Catalog path prefix** (:data:`POOL_PATH_PREFIX_MAP`) — a playbook
   whose catalog path starts with a privileged prefix (today:
   ``system/*``, see noetl/ai-meta#46 Phase 2.a.2) routes to a
   dedicated pool segment regardless of tool kind.  This is how the
   system worker pool claims platform-internal playbooks
   (``system/outbox_publisher``, ``system/projector``, …) without
   needing every step to declare a ``system_*`` tool kind.
2. **Tool kind** (:data:`POOL_FILTER_MAP`, see noetl/ai-meta#42) —
   anything not picked up by path-based routing falls back to
   kind-based routing.  The Rust noetl-worker can dispatch most tool
   kinds via the shared `noetl-tools` registry; a handful are
   Python-runtime-bound (e.g. ``agent``) and route to the Python
   pool only.

Both maps are the source of truth — the worker pools learn what they
support by *which NATS consumer they subscribe to*, not by querying
a runtime contract.  Adding a new privileged namespace or a new
Python-only kind is a one-line entry here.

:func:`route_subject` returns the legacy single subject until the
:envvar:`NOETL_COMMAND_ROUTING_ENABLED` env flag flips.  Once
enabled, the hierarchical subject ``<base>.<pool>.<execution_id>``
is used; the system pool's NATS consumer
(``filter_subject=noetl.commands.system.>``) picks up the
privileged stream.
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

# Catalog-path prefixes that route to a privileged pool regardless of
# tool kind.  The system worker pool (see noetl/ai-meta#46) runs
# platform-internal playbooks under the ``system/`` namespace; every
# command issued by such a playbook is routed to the
# ``system`` pool segment so user-pool workers cannot claim it.
#
# Order matters only if two prefixes overlap — they don't today.
# Adding a new privileged namespace: one entry here, plus a worker
# pool whose NATS consumer's ``filter_subject`` matches
# ``noetl.commands.<segment>.>``.
POOL_PATH_PREFIX_MAP: dict[str, str] = {
    "system/": "system",
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


def pool_segment_for_path(playbook_path: Optional[str]) -> Optional[str]:
    """Return the pool segment for a privileged playbook path, or ``None``.

    A playbook whose catalog path starts with any of the prefixes in
    :data:`POOL_PATH_PREFIX_MAP` routes to a dedicated pool segment
    regardless of tool kind.  The system worker pool (see
    noetl/ai-meta#46) uses this for the ``system/`` namespace so that
    ``system/outbox_publisher`` (with ``tool: http`` + ``tool: nats``
    steps that would otherwise route to ``shared``) lands on the
    privileged consumer.

    Returns ``None`` when the path doesn't match a privileged prefix
    so the caller can fall back to :func:`pool_segment_for_kind`.

    Leading slashes are stripped before matching, so both
    ``"system/outbox_publisher"`` and ``"/system/outbox_publisher"``
    resolve identically.
    """
    if not playbook_path:
        return None
    normalized = playbook_path.lstrip("/")
    if not normalized:
        return None
    for prefix, segment in POOL_PATH_PREFIX_MAP.items():
        if normalized.startswith(prefix):
            return segment
    return None


def route_subject(
    base_subject: str,
    tool_kind: Optional[str],
    execution_id: int,
    *,
    playbook_path: Optional[str] = None,
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

    Pool resolution order:

    1. :func:`pool_segment_for_path` — privileged playbook paths
       (``system/*`` etc.) win regardless of tool kind.  This is how
       a ``system/outbox_publisher`` playbook's ``tool: http`` steps
       reach the system pool instead of being claimed by a user pool.
    2. :func:`pool_segment_for_kind` — falls back to tool-kind-based
       routing (``agent`` → ``python``, everything else → ``shared``).
    """
    if not is_routing_enabled():
        return base_subject
    pool = pool_segment_for_path(playbook_path) or pool_segment_for_kind(tool_kind)
    return f"{base_subject}.{pool}.{execution_id}"


def command_stream_subjects(base_subject: str) -> list[str]:
    """Return the JetStream subject list a command stream must accept.

    Includes both the legacy bare subject (``noetl.commands`` — what
    publishes use when routing is disabled or for the transitional
    period before PR-5 flag flip) AND the hierarchical wildcard
    (``noetl.commands.>`` — what :func:`route_subject` derives when
    routing is enabled, e.g. ``noetl.commands.python.<execution_id>``).

    A NATS subject like ``X.>`` matches one-or-more tokens after the
    dot but NOT the bare ``X``, so both entries are required during
    the transition.  The cleanup PR (PR-6 per the noetl/ai-meta#42
    plan) drops the bare entry once all publishes have moved to the
    hierarchical form.
    """
    return [base_subject, f"{base_subject}.>"]


__all__ = [
    "POOL_FILTER_MAP",
    "POOL_PATH_PREFIX_MAP",
    "DEFAULT_POOL_SEGMENT",
    "ROUTING_ENABLED_ENV",
    "command_stream_subjects",
    "is_routing_enabled",
    "pool_segment_for_kind",
    "pool_segment_for_path",
    "route_subject",
]
