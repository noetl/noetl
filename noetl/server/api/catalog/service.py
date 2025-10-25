"""
Catalog storage service for NoETL catalog resources.

Provides unified catalog resource lookup and management with multiple
lookup strategies: catalog_id, path + version.
"""
from __future__ import annotations
from typing import Optional, Dict, Any, List
from datetime import datetime
import yaml
from psycopg.rows import dict_row
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection
from .schema import CatalogEntry, CatalogEntries


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

    # @staticmethod
    # async def resolve_catalog_entry(
    #     catalog_id: Optional[str] = None,
    #     path: Optional[str] = None,
    #     version: Optional[int] = None
    # ) -> CatalogEntry:
    #     """
    #     Resolve catalog entry from identifiers.
        
    #     Args:
    #         catalog_id: Direct catalog ID lookup
    #         path: Resource path for path-based lookup
    #         version: Optional version (defaults to latest if not provided)
        
    #     Returns:
    #         CatalogEntry with resolved metadata
        
    #     Raises:
    #         ValueError: If catalog entry not found or invalid
    #         RuntimeError: If database error occurs
    #     """
    #     resource_content = await CatalogService._get_resource(
    #         catalog_id=catalog_id,
    #         path=path,
    #         version=version
    #     )
        
    #     if not resource_content:
    #         identifier = catalog_id or f"{path}@{version or 'latest'}"
    #         raise ValueError(f"Catalog entry not found: {identifier}")
        
    #     return CatalogEntry(
    #         path=resource_content.path,
    #         version=str(resource_content.version),
    #         content=resource_content.content,
    #         catalog_id=str(resource_content.catalog_id)
    #     )
    
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
        return await CatalogService._fetch_entry(
            catalog_id=catalog_id,
            path=path,
            version=version
        )

    @staticmethod
    async def _fetch_entry(
        catalog_id: Optional[str] = None,
        path: Optional[str] = None,
        version: Optional[int | str] = None
    ) -> CatalogEntry | None:
        """
        Execute database query to retrieve complete catalog resource.
        
        Handles 'latest' version resolution automatically.
        
        Args:
            catalog_id: Direct catalog ID lookup
            path: Resource path
            version: Optional version (int, str, or 'latest'; defaults to latest if not provided)
            
        Returns:
            CatalogResource if found, None otherwise
            
        Raises:
            RuntimeError: If database error occurs
        """
        # # Handle "latest" version string or None
        # version_int: Optional[int] = None
        #c if version == "latest"
        #     version_int = None
        # elif isinstance(version, str):
        #     version_int = int(version)
        # else:
        #     version_int = version
        
        query, params = CatalogService._build_query(
            catalog_id=catalog_id,
            path=path,
            version=None if version is None or version == "latest" else int(version)
        )
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(query, params)
                row = await cur.fetchone()
                return CatalogEntry(**row) if row else None

    @staticmethod
    async def get_catalog_id(resource_path: str, version: str | int) -> Optional[int]:
        """Get catalog_id for a given path and version"""
        resource = await CatalogService._get_resource(
            path=resource_path,
            version=version
        )
        return int(resource.catalog_id) if resource else None

    @staticmethod
    async def get_latest_version(resource_path: str) -> int:
        """Get the latest version number for a given resource path"""
        async with get_pool_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT MAX(version) as max_version FROM noetl.catalog WHERE path = %(path)s",
                    {"path": resource_path}
                )
                row = await cur.fetchone()
                if row and row.get('max_version') is not None:
                    return int(row['max_version'])
                return 0  # Return 0 so that first version will be 1

    # @staticmethod
    # async def fetch_entry(path: str, version: str | int = "latest") -> Optional[CatalogResource]:
    #     """
    #     Fetch a catalog entry by path and version (supports 'latest').
        
    #     Args:
    #         path: Resource path
    #         version: Version number (int), version string, or 'latest' (default)
            
    #     Returns:
    #         CatalogResource if found, None otherwise
    #     """
    #     return await CatalogService._get_resource(path=path, version=version)

    def increment_version(self, version: int) -> int:
        return version + 1

    @staticmethod
    async def register_resource(content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
        resource_data = yaml.safe_load(content) or {}
        path = (resource_data.get("metadata") or {}).get("path") or resource_data.get("path") or (
            resource_data.get("metadata") or {}).get("name") or resource_data.get("name") or "unknown"

        # Get the latest version for this resource and increment it
        latest_version = await CatalogService.get_latest_version(path)
        new_version = latest_version + 1

        async with get_pool_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT INTO noetl.resource (name) VALUES (%s) ON CONFLICT DO NOTHING", (resource_type,))

                
                await cursor.execute(
                    """
                    INSERT INTO noetl.catalog
                    (path, version, kind, content, payload, meta)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING catalog_id, version
                    """,
                    (
                        path,
                        new_version,
                        resource_type,
                        content,
                        Json(resource_data),
                        Json({"registered_at": datetime.now().astimezone().isoformat()}),
                    )
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

    async def fetch_entries(self, resource_type: Optional[str] = None) -> List[CatalogEntry]:
        """List all catalog entries, optionally filtered by resource type"""
        query, params = CatalogService._build_query_filter(resource_type=resource_type)
        return await CatalogService._fetch_filter(query, params)
        # async with get_pool_connection() as conn:
        #     async with conn.cursor(row_factory=dict_row) as cur:
        #         await cur.execute(query, params)
        #         rows = await cur.fetchall() or []
        #         return CatalogEntries(entries=[CatalogEntry(**dict(r)) for r in rows])
    
    @staticmethod
    def _build_query_filter(
        resource_type: Optional[str] = None,
        path: Optional[str] = None
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
            conditions.append("AND c.kind = %(resource_type)s")
            params["resource_type"] = resource_type
        
        if path:
            conditions.append("AND c.path = %(path)s")
            params["path"] = path
        
        order_clause = "ORDER BY c.created_at DESC"
        
        parts = [base_query]
        if conditions:
            parts.extend(conditions)
        parts.append(order_clause)
        
        return " ".join(parts), params
    
    @staticmethod
    async def _fetch_filter(query: str, params: Dict[str, Any]) -> List[CatalogEntry]:
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
