"""Resolve catalog_id → playbook path (with in-process LRU cache).

Used by command-emit call sites that need the playbook path for
:func:`noetl.core.runtime.pool_routing.route_subject` but only have
``catalog_id`` in scope (the batch + event endpoints already passed
``cat_id`` through every command).

Catalog rows are immutable per ``(path, version)`` tuple — once a
``catalog_id`` is assigned its ``path`` never changes — so the cache
has no TTL.  An LRU bound keeps memory predictable across the long-
lived server process.

If the cache miss query fails (DB unavailable, row deleted), the
helper logs a warning and returns ``None``; the caller falls back to
tool-kind-based routing, which preserves today's behaviour.
"""

from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

logger = logging.getLogger(__name__)

# Bound the cache size.  Server typically sees < 100 active playbook
# paths per tenant per day; 1024 entries keeps every realistic
# workload pinned without growing the heap unboundedly under
# pathological load.
_CACHE_MAX_ENTRIES = 1024

# OrderedDict gives us O(1) LRU: ``move_to_end`` on hit, ``popitem``
# on overflow.  Keyed by ``int(catalog_id)``; value is the path
# string or ``None`` (negative cache for catalog_ids that don't
# exist, so a misconfigured caller doesn't hammer the DB).
_cache: "OrderedDict[int, Optional[str]]" = OrderedDict()


def _cache_get(catalog_id: int) -> tuple[bool, Optional[str]]:
    """Return ``(hit, value)`` — ``hit=False`` means miss, ``value`` is meaningless."""
    if catalog_id in _cache:
        value = _cache[catalog_id]
        _cache.move_to_end(catalog_id)
        return True, value
    return False, None


def _cache_set(catalog_id: int, path: Optional[str]) -> None:
    _cache[catalog_id] = path
    _cache.move_to_end(catalog_id)
    while len(_cache) > _CACHE_MAX_ENTRIES:
        _cache.popitem(last=False)


def cache_clear() -> None:
    """Drop every cached entry.  Used by tests."""
    _cache.clear()


async def catalog_path_for(catalog_id: Optional[int]) -> Optional[str]:
    """Return the playbook catalog path for ``catalog_id``, or ``None``.

    Hits a process-local LRU cache (no TTL — catalog rows are
    immutable per id) backed by a single-row ``SELECT path FROM
    noetl.catalog WHERE catalog_id = %s`` on miss.

    ``None`` input or DB error → ``None`` (the caller's routing falls
    back to tool-kind-based segmentation, same as today).
    """
    if catalog_id is None:
        return None
    try:
        cid = int(catalog_id)
    except (TypeError, ValueError):
        return None

    hit, value = _cache_get(cid)
    if hit:
        return value

    try:
        # Import here to avoid a circular import at module load time
        # (noetl.core.db.pool → server config → this module via the
        # core package's re-exports).
        from noetl.core.db.pool import get_pool_connection

        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT path FROM noetl.catalog WHERE catalog_id = %s",
                    (cid,),
                )
                row = await cur.fetchone()
    except Exception as exc:
        logger.warning(
            "catalog_path_for lookup failed for catalog_id=%s: %s",
            cid,
            exc,
        )
        return None

    path: Optional[str] = None
    if row is not None:
        # psycopg's default for our pool is ``dict_row`` but some call
        # sites override; accept either shape defensively.
        if isinstance(row, dict):
            path = row.get("path")
        else:
            try:
                path = row[0]
            except (IndexError, TypeError):
                path = None
        if path is not None:
            path = str(path)

    _cache_set(cid, path)
    return path


__all__ = [
    "cache_clear",
    "catalog_path_for",
]
