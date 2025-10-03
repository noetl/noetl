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

    async def get_latest_version(self, resource_path: str) -> str:
        try:
            async with get_async_db_connection(self.pgdb_conn_string) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COUNT(*) FROM catalog WHERE resource_path = %s",
                        (resource_path,),
                    )
                    row = await cursor.fetchone()
                    count = int(row[0]) if row else 0
                    if count == 0:
                        return "0.1.0"

                    await cursor.execute(
                        "SELECT resource_version FROM catalog WHERE resource_path = %s",
                        (resource_path,),
                    )
                    versions = [r[0] for r in (await cursor.fetchall() or [])]
                    if not versions:
                        return "0.1.0"

                    def _version_key(v: str):
                        parts = (v or "0").split('.')
                        parts += ['0'] * (3 - len(parts))
                        try:
                            return tuple(map(int, parts[:3]))
                        except Exception:
                            return (0, 0, 0)

                    latest = max(versions, key=_version_key)
                    return latest
        except Exception:
            return "0.1.0"

    async def fetch_entry(self, path: str, version: str) -> Optional[Dict[str, Any]]:
        try:
            # Handle "latest" version by getting the actual latest version
            if version == "latest":
                version = await self.get_latest_version(path)
                if not version:
                    return None

            async with get_async_db_connection(self.pgdb_conn_string) as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    await cursor.execute(
                        """
                        SELECT resource_path, resource_type, resource_version, content, payload, meta
                        FROM catalog
                        WHERE resource_path = %s AND resource_version = %s
                        """,
                        (path, version)
                    )
                    result = await cursor.fetchone()
                    if result:
                        return dict(result)
                    return None
        except Exception:
            return None

    def increment_version(self, version: str) -> str:
        try:
            parts = (version or "0").split('.')
            while len(parts) < 3:
                parts.append('0')
            major, minor, patch = map(int, parts[:3])
            patch += 1
            return f"{major}.{minor}.{patch}"
        except Exception:
            return f"{version}.1"

    async def register_resource(self, content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
        try:
            resource_data = yaml.safe_load(content) or {}
            resource_path = (resource_data.get("metadata") or {}).get("path") or resource_data.get("path") or (
                resource_data.get("metadata") or {}).get("name") or resource_data.get("name") or "unknown"
            # Determine latest version synchronously from DB
            latest = None
            try:
                async with get_async_db_connection(self.pgdb_conn_string) as _conn:
                    async with _conn.cursor() as _cur:
                        await _cur.execute("SELECT resource_version FROM catalog WHERE resource_path = %s", (resource_path,))
                        _versions = [r[0] for r in (await _cur.fetchall() or [])]
                        if _versions:
                            def _version_key(v: str):
                                p = (v or "0").split('.')
                                p += ['0'] * (3 - len(p))
                                try:
                                    return tuple(map(int, p[:3]))
                                except Exception:
                                    return (0, 0, 0)
                            latest = max(_versions, key=_version_key)
            except Exception:
                latest = None
            latest = latest or "0.1.0"
            resource_version = latest if latest == '0.1.0' else self.increment_version(
                latest)

            async with get_async_db_connection(self.pgdb_conn_string) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("INSERT INTO resource (name) VALUES (%s) ON CONFLICT DO NOTHING", (resource_type,))

                    attempt = 0
                    while attempt < 5:
                        await cursor.execute(
                            "SELECT COUNT(*) FROM catalog WHERE resource_path = %s AND resource_version = %s",
                            (resource_path, resource_version)
                        )
                        row = await cursor.fetchone()
                        if not row or int(row[0]) == 0:
                            break
                        resource_version = self.increment_version(
                            resource_version)
                        attempt += 1
                    if attempt >= 5:
                        raise RuntimeError("Failed to find unique version")

                    from psycopg.types.json import Json
                    await cursor.execute(
                        """
                        INSERT INTO catalog
                        (resource_path, resource_type, resource_version, content, payload, meta)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            resource_path,
                            resource_type,
                            resource_version,
                            content,
                            Json(resource_data),
                            Json({"registered_at": datetime.utcnow().isoformat()}),
                        )
                    )
                    try:
                        await conn.commit()
                    except Exception:
                        pass

            return {
                "status": "success",
                "message": f"Resource '{resource_path}' version '{resource_version}' registered.",
                "resource_path": resource_path,
                "resource_version": resource_version,
                "resource_type": resource_type,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def list_entries(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            async with get_async_db_connection(self.pgdb_conn_string) as conn:
                async with conn.cursor(row_factory=dict_row) as cursor:
                    if resource_type:
                        await cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                            FROM catalog WHERE resource_type = %s ORDER BY timestamp DESC
                            """,
                            (resource_type,)
                        )
                    else:
                        await cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                            FROM catalog ORDER BY timestamp DESC
                            """
                        )
                    rows = await cursor.fetchall() or []
                    return [dict(r) for r in rows]
        except Exception:
            return []

    async def entry_all_versions(self, resource_path: str) -> list[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                        SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                        FROM catalog WHERE resource_path = %s ORDER BY timestamp DESC
                        """,
                    (resource_path,)
                )
                # rows = await cursor.fetchall()
                return await cursor.fetchall()


def get_catalog_service() -> CatalogService:
    return CatalogService()
