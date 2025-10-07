"""
Catalog storage DAO moved under server API catalog package.
"""
from __future__ import annotations

from typing import Optional, Dict, Any, List
from datetime import datetime
import yaml
from psycopg.rows import dict_row

from noetl.core.common import get_async_db_connection, get_pgdb_connection


class CatalogService:
    def __init__(self, pgdb_conn_string: str | None = None):
        self.pgdb_conn_string = pgdb_conn_string or get_pgdb_connection()

    async def get_catalog_id(self, resource_path: str, version: str | int) -> Optional[int]:
        """Get catalog_id for a given path and version"""
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT catalog_id FROM noetl.catalog WHERE path = %s AND version = %s",
                    (resource_path, int(version) if version else 1),
                )
                row = await cursor.fetchone()
                if row:
                    return row[0]
                return None

    async def get_latest_version(self, resource_path: str) -> int:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT MAX(version) FROM noetl.catalog WHERE path = %s",
                    (resource_path,),
                )
                row = await cursor.fetchone()
                if row and row[0] is not None:
                    return int(row[0])
                return 0  # Return 0 so that first version will be 1

    async def fetch_entry(self, path: str, version: str | int) -> Optional[Dict[str, Any]]:
        # Handle "latest" version by getting the actual latest version
        if version == "latest":
            version = await self.get_latest_version(path)
            if not version:
                return None

        # Convert version to int
        version_int = int(version) if version else 1

        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT c.catalog_id, c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.created_at
                    FROM noetl.catalog c
                    WHERE c.path = %s AND c.version = %s
                    """,
                    (path, version_int)
                )
                result = await cursor.fetchone()
                if result:
                    return dict(result)
                return None

    def increment_version(self, version: int) -> int:
        return version + 1

    async def register_resource(self, content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
        resource_data = yaml.safe_load(content) or {}
        path = (resource_data.get("metadata") or {}).get("path") or resource_data.get("path") or (
            resource_data.get("metadata") or {}).get("name") or resource_data.get("name") or "unknown"

        # Get the latest version for this resource and increment it
        latest_version = await self.get_latest_version(path)
        new_version = latest_version + 1

        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT INTO noetl.resource (name) VALUES (%s) ON CONFLICT DO NOTHING", (resource_type,))

                from psycopg.types.json import Json
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
                catalog_id = result[0] if result else None
                version = result[1] if result else new_version

                await conn.commit()

        return {
            "status": "success",
            "message": f"Resource '{path}' version '{version}' registered.",
            "path": path,
            "version": version,
            "catalog_id": catalog_id,
            "kind": resource_type,
        }

    async def list_entries(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                if resource_type:
                    await cursor.execute(
                        """
                        SELECT c.catalog_id, c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.created_at
                        FROM noetl.catalog c
                        WHERE c.kind = %s ORDER BY c.created_at DESC
                        """,
                        (resource_type,)
                    )
                else:
                    await cursor.execute(
                        """
                        SELECT c.catalog_id, c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.created_at
                        FROM noetl.catalog c
                        ORDER BY c.created_at DESC
                        """
                    )
                rows = await cursor.fetchall() or []
                return [dict(r) for r in rows]

    async def entry_all_versions(self, resource_path: str) -> list[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                        SELECT c.catalog_id, c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.created_at
                        FROM noetl.catalog c
                        WHERE c.path = %s ORDER BY c.created_at DESC
                        """,
                    (resource_path,)
                )
                # rows = await cursor.fetchall()
                return await cursor.fetchall()


def get_catalog_service() -> CatalogService:
    return CatalogService()
