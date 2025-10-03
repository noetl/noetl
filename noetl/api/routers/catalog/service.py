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
                return 1

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
                    SELECT c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.timestamp
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
        resource_path = (resource_data.get("metadata") or {}).get("path") or resource_data.get("path") or (
            resource_data.get("metadata") or {}).get("name") or resource_data.get("name") or "unknown"

        # Get the latest version for this resource
        latest_version = await self.get_latest_version(resource_path)

        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("INSERT INTO noetl.resource (name) VALUES (%s) ON CONFLICT DO NOTHING", (resource_type,))

                from psycopg.types.json import Json
                # Insert new version - version will auto-increment via SMALLSERIAL
                await cursor.execute(
                    """
                    INSERT INTO noetl.catalog
                    (path, kind, content, payload, meta)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING version
                    """,
                    (
                        resource_path,
                        resource_type,
                        content,
                        Json(resource_data),
                        Json({"registered_at": datetime.now().astimezone().isoformat()}),
                    )
                )
                result = await cursor.fetchone()
                resource_version = result[0] if result else latest_version

                await conn.commit()

        return {
            "status": "success",
            "message": f"Resource '{resource_path}' version '{resource_version}' registered.",
            "resource_path": resource_path,
            "resource_version": resource_version,
            "resource_type": resource_type,
        }

    async def list_entries(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                if resource_type:
                    await cursor.execute(
                        """
                        SELECT c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.timestamp
                        FROM noetl.catalog c
                        WHERE c.kind = %s ORDER BY c.timestamp DESC
                        """,
                        (resource_type,)
                    )
                else:
                    await cursor.execute(
                        """
                        SELECT c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.timestamp
                        FROM noetl.catalog c
                        ORDER BY c.timestamp DESC
                        """
                    )
                rows = await cursor.fetchall() or []
                return [dict(r) for r in rows]

    async def entry_all_versions(self, resource_path: str) -> list[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                        SELECT c.path, c.version, c.kind, c.content, c.layout, c.payload, c.meta, c.timestamp
                        FROM noetl.catalog c
                        WHERE c.path = %s ORDER BY c.timestamp DESC
                        """,
                    (resource_path,)
                )
                # rows = await cursor.fetchall()
                return await cursor.fetchall()


def get_catalog_service() -> CatalogService:
    return CatalogService()
