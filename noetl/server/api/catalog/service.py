"""
Catalog storage service for NoETL catalog resources.

Provides unified catalog resource lookup and management with multiple
lookup strategies: catalog_id, path + version.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List, Coroutine
from datetime import datetime
from collections import OrderedDict
import time
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection
from .schema import CatalogEntry, CatalogEntries
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


# ==================== Catalog Cache ====================

class _CatalogCache:
    """
    LRU cache for catalog entries to avoid repeated database lookups.

    Cache entries expire after TTL seconds to ensure freshness.
    Memory bounded with max_size limit.
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        self._cache: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    def _make_key(self, catalog_id: Optional[str], path: Optional[str], version: Optional[int]) -> str:
        """Create cache key from lookup parameters."""
        if catalog_id:
            return f"id:{catalog_id}"
        return f"path:{path}:v:{version or 'latest'}"

    def get(self, catalog_id: Optional[str] = None, path: Optional[str] = None,
            version: Optional[int] = None) -> Optional[Any]:
        """Get entry from cache if exists and not expired."""
        key = self._make_key(catalog_id, path, version)

        if key in self._cache:
            entry, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                self._cache.move_to_end(key)
                self._hits += 1
                return entry
            else:
                # Expired, remove it
                del self._cache[key]

        self._misses += 1
        return None

    def put(self, entry: Any, catalog_id: Optional[str] = None,
            path: Optional[str] = None, version: Optional[int] = None) -> None:
        """Put entry in cache."""
        key = self._make_key(catalog_id, path, version)

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size:
            self._cache.popitem(last=False)

        self._cache[key] = (entry, time.time())

        # Also cache by catalog_id if we have it
        if entry and hasattr(entry, 'catalog_id') and entry.catalog_id:
            id_key = f"id:{entry.catalog_id}"
            if id_key != key:
                self._cache[id_key] = (entry, time.time())

    def invalidate(self, catalog_id: Optional[str] = None, path: Optional[str] = None) -> None:
        """Invalidate cache entries."""
        keys_to_remove = []
        for key in self._cache:
            if catalog_id and f"id:{catalog_id}" == key:
                keys_to_remove.append(key)
            elif path and key.startswith(f"path:{path}:"):
                keys_to_remove.append(key)
        for key in keys_to_remove:
            del self._cache[key]

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": (self._hits / total * 100) if total > 0 else 0.0
        }


# Global catalog cache instance
_catalog_cache = _CatalogCache(max_size=100, ttl_seconds=300)


# class CatalogEntry(AppBaseModel):
#     """Resolved catalog entry with minimal required metadata."""
#     path: str
#     version: str
#     content: str
#     catalog_id: str


class CatalogService:
    """
    Service class for catalog resource management.
    
    Responsibilities:
    - Catalog entry lookup by catalog_id or path+version
    - Resource registration and versioning
    - Catalog listing and querying
    """
    
    @staticmethod
    def _build_query(        
        catalog_id: Optional[str] = None,
        path: Optional[str] = None,
        version: Optional[int] = None
    ) -> tuple[str, Dict[str, Any]]:
        """
        Build SQL query for catalog lookup.
        
        Supports:
        - Direct lookup by catalog_id
        - Path-based lookup with optional version (defaults to latest)
        """
        base_query = "SELECT catalog_id, path, version, kind, content, layout, payload, meta, created_at FROM noetl.catalog"
        params: Dict[str, Any] = {}

        if catalog_id:
            where_clause = "catalog_id = %(catalog_id)s"
            params["catalog_id"] = catalog_id
            order_clause = ""
        else:
            clauses = ["path = %(path)s"]
            params["path"] = path
            if version is not None:
                clauses.append("version = %(version)s")
                params["version"] = version
                order_clause = ""
            else:
                order_clause = "ORDER BY version DESC"
            where_clause = " AND ".join(clauses)

        parts = [f"{base_query} WHERE {where_clause}"]
        if order_clause:
            parts.append(order_clause)
        parts.append("LIMIT 1")

        return " ".join(parts), params

    @staticmethod
    async def get(
        catalog_id: Optional[str] = None,
        path: Optional[str] = None, 
        version: Optional[int | str] = None
        ) -> CatalogEntry | None:
        """
        Get a catalog resource by its identifiers.
        """
        return await CatalogService.fetch_entry(
            catalog_id=catalog_id,
            path=path,
            version=version
        )

    @staticmethod
    async def fetch_entry(
        catalog_id: Optional[str] = None,
        path: Optional[str] = None,
        version: Optional[int | str] = None,
        use_cache: bool = True
    ) -> CatalogEntry | None:
        """
        Execute database query to retrieve complete catalog resource.

        Handles 'latest' version resolution automatically.
        Uses LRU cache to avoid repeated database lookups.

        Args:
            catalog_id: Direct catalog ID lookup
            path: Resource path
            version: Optional version (int, str, or 'latest'; defaults to latest if not provided)
            use_cache: Whether to use cache (default True)

        Returns:
            CatalogResource if found, None otherwise

        Raises:
            RuntimeError: If database error occurs
        """
        version_int = None if version is None or version == "latest" else int(version)

        # Check cache first
        if use_cache:
            cached = _catalog_cache.get(catalog_id=catalog_id, path=path, version=version_int)
            if cached is not None:
                logger.debug(f"Catalog cache hit: catalog_id={catalog_id}, path={path}")
                return cached

        query, params = CatalogService._build_query(
            catalog_id=catalog_id,
            path=path,
            version=version_int
        )
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                entry = CatalogEntry(**row) if row else None

        # Store in cache
        if use_cache and entry:
            _catalog_cache.put(entry, catalog_id=catalog_id, path=path, version=version_int)

        return entry

    @staticmethod
    def get_cache_stats() -> dict:
        """Get catalog cache statistics."""
        return _catalog_cache.stats()

    @staticmethod
    def invalidate_cache(catalog_id: Optional[str] = None, path: Optional[str] = None) -> None:
        """Invalidate catalog cache entries."""
        _catalog_cache.invalidate(catalog_id=catalog_id, path=path)

    
    @staticmethod
    async def fetch_resource_template(
        resource_path: str,
        version: Optional[int] = None
    ) -> Optional[dict[str, Any]]:
        """Fetch catalog entry by path and version (None for latest)"""
        entry = await CatalogService.fetch_entry(
            path=resource_path,
            version=version
        )
        if entry and entry.content:
            return yaml.safe_load(entry.content)
        return None
    
    @staticmethod
    async def get_catalog_id(resource_path: str, version: str | int) -> Optional[int]:
        """Get catalog_id for a given path and version"""
        resource = await CatalogService.get(
            path=resource_path,
            version=version
        )
        return int(resource.catalog_id) if resource else None

    @staticmethod
    async def get_latest_version(resource_path: str) -> int:
        """Get the latest version number for a given resource path"""
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT MAX(version) as max_version FROM noetl.catalog WHERE path = %(path)s",
                    {"path": resource_path}
                )
                row = await cur.fetchone()
                if row and row.get('max_version') is not None:
                    return int(row['max_version'])
                return 0  # Return 0 so that first version will be 1


    @staticmethod
    def increment_version(version: int) -> int:
        return version + 1

    @staticmethod
    def _is_truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _extract_agent_metadata(resource_data: Dict[str, Any]) -> Dict[str, Any]:
        metadata = resource_data.get("metadata") if isinstance(resource_data, dict) else {}
        metadata = metadata if isinstance(metadata, dict) else {}
        capabilities = metadata.get("capabilities")
        if isinstance(capabilities, list):
            normalized_capabilities = [str(c).strip() for c in capabilities if str(c).strip()]
        elif isinstance(capabilities, str) and capabilities.strip():
            normalized_capabilities = [capabilities.strip()]
        else:
            normalized_capabilities = []

        terminal = metadata.get("terminal")
        terminal = terminal if isinstance(terminal, dict) else {}
        terminal_scopes = terminal.get("scopes") or terminal.get("scope") or []
        if isinstance(terminal_scopes, str):
            normalized_terminal_scopes = [scope.strip() for scope in terminal_scopes.split(",") if scope.strip()]
        elif isinstance(terminal_scopes, list):
            normalized_terminal_scopes = [str(scope).strip() for scope in terminal_scopes if str(scope).strip()]
        else:
            normalized_terminal_scopes = []

        return {
            "agent": CatalogService._is_truthy(metadata.get("agent", False)),
            "capabilities": normalized_capabilities,
            "terminal": terminal,
            "terminal_visible": CatalogService._is_truthy(terminal.get("visible", False)),
            "terminal_scopes": normalized_terminal_scopes,
        }

    @staticmethod
    def _normalize_resource_type(resource_type: Optional[str]) -> str:
        value = str(resource_type or "playbook").strip()
        if not value:
            return "playbook"
        aliases = {
            "Playbook": "playbook",
            "Credential": "credential",
            "Credentials": "credential",
            "Secret": "credential",
            "Secrets": "credential",
            "MCP": "mcp",
            "ModelContextProtocol": "mcp",
            "Agent": "agent",
            "Memory": "memory",
        }
        return aliases.get(value, value).strip().lower()

    @staticmethod
    def _resolve_resource_kind(*, payload: Any, fallback: Optional[str]) -> str:
        """Resolve the catalog kind for a registration request.

        The YAML's own ``kind:`` field is authoritative — the request
        ``resource_type`` parameter is a hint that callers (e.g. the
        CLI's ``noetl catalog register``) tend to default to
        "Playbook" without sniffing the file. Without this precedence,
        an ``kind: Mcp`` template registered via the catch-all
        ``catalog register`` path lands in the catalog as
        ``kind: playbook`` and downstream lookups (e.g.
        ``fetch_mcp_resource``, which guards
        ``kind.lower() == "mcp"``) reject it as the wrong type.

        Fall back to the request parameter only when the payload
        doesn't declare a kind. Both branches go through
        ``_normalize_resource_type`` so the alias table is the single
        place that knows ``MCP``/``Mcp``/``mcp`` collapse to ``mcp``.
        """
        payload_kind = payload.get("kind") if isinstance(payload, dict) else None
        if isinstance(payload_kind, str) and payload_kind.strip():
            return CatalogService._normalize_resource_type(payload_kind)
        return CatalogService._normalize_resource_type(fallback)

    @staticmethod
    def _resource_type_meta(resource_type: str) -> Dict[str, Any]:
        catalog_types = {
            "playbook": {
                "description": "Executable NoETL workflow definition",
                "executable": True,
                "catalog": True,
            },
            "credential": {
                "description": "Credential or secret reference metadata",
                "executable": False,
                "catalog": True,
            },
            "mcp": {
                "description": "Model Context Protocol server/tool provider",
                "executable": False,
                "catalog": True,
            },
            "agent": {
                "description": "Agent-as-playbook or agent capability resource",
                "executable": True,
                "catalog": True,
            },
            "memory": {
                "description": "AI memory, knowledge, or coordination artifact",
                "executable": False,
                "catalog": True,
            },
        }
        return catalog_types.get(resource_type, {"catalog": True})

    @staticmethod
    async def register_resource(content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
        resource_data = yaml.safe_load(content) or {}
        resource_type = CatalogService._resolve_resource_kind(
            payload=resource_data,
            fallback=resource_type,
        )
        path = (resource_data.get("metadata") or {}).get("path") or resource_data.get("path") or (
            resource_data.get("metadata") or {}).get("name") or resource_data.get("name") or "unknown"

        # Inject implicit "end" step if playbook doesn't have one
        if resource_type in {"playbook", "agent"}:
            workflow = resource_data.get("workflow", [])
            if workflow and not any(step.get("step", "").lower() == "end" for step in workflow):
                logger.info(f"CATALOG: Injecting implicit 'end' step for playbook '{path}'")
                workflow.append({
                    "step": "end",
                    "desc": "Implicit workflow aggregator (auto-injected)",
                    "tool": {
                        "kind": "python",
                        "code": "def main():\n    # Implicit end step - aggregates all workflow results\n    return {'status': 'aggregated'}"
                    }
                })
                resource_data["workflow"] = workflow

        # Get the latest version for this resource and increment it
        latest_version = await CatalogService.get_latest_version(path)
        new_version = latest_version + 1

        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    INSERT INTO noetl.resource (name, meta)
                    VALUES (%(resource_type)s, %(resource_meta)s)
                    ON CONFLICT (name) DO UPDATE
                    SET meta = COALESCE(noetl.resource.meta, '{}'::jsonb) || EXCLUDED.meta
                    """,
                    {
                        "resource_type": resource_type,
                        "resource_meta": Json(CatalogService._resource_type_meta(resource_type)),
                    }
                )

                
                await cursor.execute(
                    """
                    INSERT INTO noetl.catalog (
                        path,
                        version,
                        kind,
                        content,
                        payload,
                        meta
                    ) VALUES (
                        %(path)s,
                        %(version)s,
                        %(kind)s,
                        %(content)s,
                        %(payload)s,
                        %(meta)s
                    )
                    RETURNING catalog_id, version
                    """,
                    {
                        "path": path,
                        "version": new_version,
                        "kind": resource_type,
                        "content": content,
                        "payload": Json(resource_data),
                        "meta": Json(
                            {
                                "registered_at": datetime.now().astimezone().isoformat(),
                                **CatalogService._extract_agent_metadata(resource_data),
                            }
                        ),
                    }
                )
                result = await cursor.fetchone()
                catalog_id = result['catalog_id'] if result else None
                version = result['version'] if result else new_version

                await conn.commit()

        return {
            "status": "success",
            "message": f"Resource '{path}' version '{version}' registered.",
            "path": path,
            "version": version,
            "catalog_id": catalog_id,
            "kind": resource_type,
        }

    @staticmethod
    async def fetch_entries(
        resource_type: Optional[str] = None,
        path: Optional[str] = None,
        agent_only: bool = False,
        capabilities: Optional[List[str]] = None,
    ) -> List[CatalogEntry]:
        """List all catalog entries, optionally filtered by resource type"""
        query, params = CatalogService._build_query_filter(
            resource_type=resource_type,
            path=path,
            agent_only=agent_only,
            capabilities=capabilities,
        )
        return await CatalogService._fetch_filter(query, params)

    @staticmethod
    async def fetch_agent_entries(
        path: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
    ) -> List[CatalogEntry]:
        """List catalog entries marked as agents, optionally filtered by capability/path."""
        return await CatalogService.fetch_entries(
            resource_type=None,
            path=path,
            agent_only=True,
            capabilities=capabilities,
        )
    
    @staticmethod
    def _build_query_filter(
        resource_type: Optional[str] = None,
        path: Optional[str] = None,
        agent_only: bool = False,
        capabilities: Optional[List[str]] = None,
    ) -> tuple[str, Dict[str, Any]]:
        """
        Build SQL query for listing catalog entries.
        
        Args:
            resource_type: Filter by resource kind
            path: Filter by resource path (for all versions)
        
        Returns:
            Tuple of (query_string, parameters)
        """
        base_query = """
            SELECT c.catalog_id, c.path, c.version, c.kind, c.content, 
                   c.layout, c.payload, c.meta, c.created_at
            FROM noetl.catalog c
            WHERE 1=1
        """
        params: Dict[str, Any] = {}
        conditions = []
        
        if resource_type:
            conditions.append("AND lower(c.kind) = %(resource_type)s")
            params["resource_type"] = CatalogService._normalize_resource_type(resource_type)
        
        if path:
            conditions.append("AND c.path = %(path)s")
            params["path"] = path

        if agent_only:
            conditions.append(
                """
                AND (
                    lower(c.kind) = 'agent'
                    OR lower(coalesce(c.payload->'metadata'->>'agent', c.meta->>'agent', 'false')) IN ('1', 'true', 'yes', 'on')
                )
                """
            )

        normalized_capabilities = [str(c).strip() for c in (capabilities or []) if str(c).strip()]
        if normalized_capabilities:
            conditions.append(
                """
                AND EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements_text(
                        CASE
                            WHEN jsonb_typeof(c.payload->'metadata'->'capabilities') = 'array'
                                THEN c.payload->'metadata'->'capabilities'
                            WHEN jsonb_typeof(c.meta->'capabilities') = 'array'
                                THEN c.meta->'capabilities'
                            ELSE '[]'::jsonb
                        END
                    ) AS cap(value)
                    WHERE cap.value = ANY(%(capabilities)s)
                )
                """
            )
            params["capabilities"] = normalized_capabilities
        
        order_clause = "ORDER BY c.created_at DESC"
        
        parts = [base_query]
        if conditions:
            parts.extend(conditions)
        parts.append(order_clause)
        
        return " ".join(parts), params
    
    @staticmethod
    async def _fetch_filter(query: str, params: Dict[str, Any]) -> CatalogEntries:
        """
        Fetch a list of CatalogEntries.

        Args:
            query: SQL query string
            params: Query parameters
        
        Returns:
            List of CatalogEntry models
        """
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(query, params)
                rows = await cur.fetchall() or []
                return CatalogEntries(entries=[CatalogEntry(**dict(r)) for r in rows])


def get_catalog_service() -> CatalogService:
    return CatalogService()
