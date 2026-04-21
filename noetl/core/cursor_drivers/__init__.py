"""Cursor drivers for pull-model loops (loop.cursor).

Each driver adapts a backing store (postgres, mysql, snowflake, redis, ...)
to a uniform ``claim → process → release`` contract so workers can pull
work items atomically from a distributed queue.

Contract (see ``CursorDriver``):

- ``open(auth, spec)`` — open a connection/handle for the cursor's duration.
- ``claim(handle, context)`` — atomically claim and return one row (or None
  when the cursor is drained).  The driver is responsible for the
  atomicity guarantee (e.g. ``UPDATE ... FOR UPDATE SKIP LOCKED
  RETURNING`` for postgres, ``XREADGROUP`` for Redis streams, etc.).
- ``close(handle)`` — release the connection/handle.

Drivers register themselves via ``register_driver(kind, driver)``; the
engine and worker look up by ``cursor.kind``.  Unknown kinds raise a
``CursorDriverNotFoundError`` at load time so playbook authors get a
fast, clear failure.
"""
from __future__ import annotations

from typing import Any, Optional, Protocol, runtime_checkable


class CursorDriverError(Exception):
    """Base for cursor driver errors."""


class CursorDriverNotFoundError(CursorDriverError):
    """Raised when a playbook references an unknown cursor kind."""


@runtime_checkable
class CursorDriver(Protocol):
    """Async cursor driver contract.

    Implementations must be safe to use from multiple worker processes
    concurrently; the atomicity of ``claim`` is driver-specific.
    """

    kind: str

    async def open(self, auth: Any, spec: dict[str, Any]) -> Any:
        """Open a driver-specific handle.

        ``auth`` is the resolved credential (whatever shape the driver's
        registered credential type has).  ``spec`` is the full cursor
        spec (kind/auth/claim/options).  Returns a handle that ``claim``
        and ``close`` understand.
        """
        ...

    async def claim(
        self,
        handle: Any,
        context: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Atomically claim and return the next item.

        ``context`` carries per-claim render data (execution_id, worker
        slot id, etc.) that the driver may interpolate into its claim
        statement.  Returns a dict of column/key values, or ``None`` when
        the cursor is drained.
        """
        ...

    async def close(self, handle: Any) -> None:
        """Release the driver-specific handle."""
        ...


_registry: dict[str, CursorDriver] = {}


def register_driver(kind: str, driver: CursorDriver) -> None:
    """Register a driver under a cursor ``kind`` (e.g. ``postgres``)."""
    _registry[kind] = driver


def get_driver(kind: str) -> CursorDriver:
    """Look up a driver by kind, raising ``CursorDriverNotFoundError`` if missing."""
    try:
        return _registry[kind]
    except KeyError as exc:
        raise CursorDriverNotFoundError(
            f"No cursor driver registered for kind={kind!r}. "
            f"Available kinds: {sorted(_registry.keys()) or '[]'}"
        ) from exc


def registered_kinds() -> list[str]:
    """Return the list of registered cursor driver kinds (for diagnostics)."""
    return sorted(_registry.keys())


# Auto-register built-in drivers.
from . import postgres as _postgres  # noqa: E402,F401  (import registers)

__all__ = [
    "CursorDriver",
    "CursorDriverError",
    "CursorDriverNotFoundError",
    "register_driver",
    "get_driver",
    "registered_kinds",
]
