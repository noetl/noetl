import os
import json
import yaml
from typing import Dict, Any, Optional, List
from datetime import datetime

from psycopg.rows import dict_row
from psycopg.types.json import Json

from noetl.common import (
    deep_merge,
    get_pgdb_connection,
    get_db_connection,
    get_async_db_connection,
    get_snowflake_id_str,
    get_snowflake_id,
)
from noetl.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class CatalogService:
    def __init__(self, pgdb_conn_string: str | None = None):
        self.pgdb_conn_string = pgdb_conn_string or get_pgdb_connection()

    async def get_latest_version(self, resource_path: str) -> str:
        try:
            async with get_async_db_connection(self.pgdb_conn_string) as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(
                        "SELECT COUNT(*) FROM catalog WHERE resource_path = %s",
                        (resource_path,)
                    )
                    row = await cursor.fetchone()
                    count = int(row[0]) if row else 0
                    if count == 0:
                        return "0.1.0"

                    await cursor.execute(
                        "SELECT resource_version FROM catalog WHERE resource_path = %s",
                        (resource_path,)
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

    def fetch_entry(self, path: str, version: str) -> Optional[Dict[str, Any]]:
        try:
            with get_db_connection(self.pgdb_conn_string) as conn:
                with conn.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        """
                        SELECT resource_path, resource_type, resource_version, content, payload, meta
                        FROM catalog
                        WHERE resource_path = %s AND resource_version = %s
                        """,
                        (path, version)
                    )
                    result = cursor.fetchone()
                    if not result and '/' in path:
                        filename = path.split('/')[-1]
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta
                            FROM catalog
                            WHERE resource_path = %s AND resource_version = %s
                            """,
                            (filename, version)
                        )
                        result = cursor.fetchone()
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

    def register_resource(self, content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
        try:
            resource_data = yaml.safe_load(content)
            resource_path = resource_data.get("path", resource_data.get("name", "unknown"))
            # Determine latest version synchronously from DB
            latest = None
            try:
                with get_db_connection(self.pgdb_conn_string) as _conn:
                    with _conn.cursor() as _cur:
                        _cur.execute("SELECT resource_version FROM catalog WHERE resource_path = %s", (resource_path,))
                        _versions = [r[0] for r in (_cur.fetchall() or [])]
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
            resource_version = latest if latest == '0.1.0' else self.increment_version(latest)

            with get_db_connection(self.pgdb_conn_string) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("INSERT INTO resource (name) VALUES (%s) ON CONFLICT DO NOTHING", (resource_type,))

                    attempt = 0
                    while attempt < 5:
                        cursor.execute(
                            "SELECT COUNT(*) FROM catalog WHERE resource_path = %s AND resource_version = %s",
                            (resource_path, resource_version)
                        )
                        row = cursor.fetchone()
                        if not row or int(row[0]) == 0:
                            break
                        resource_version = self.increment_version(resource_version)
                        attempt += 1
                    if attempt >= 5:
                        raise RuntimeError("Failed to find unique version")

                    cursor.execute(
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
                        conn.commit()
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

    def list_entries(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        try:
            with get_db_connection(self.pgdb_conn_string) as conn:
                with conn.cursor(row_factory=dict_row) as cursor:
                    if resource_type:
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                            FROM catalog WHERE resource_type = %s ORDER BY timestamp DESC
                            """,
                            (resource_type,)
                        )
                    else:
                        cursor.execute(
                            """
                            SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                            FROM catalog ORDER BY timestamp DESC
                            """
                        )
                    rows = cursor.fetchall() or []
                    return [dict(r) for r in rows]
        except Exception:
            return []


class EventService:
    def __init__(self, pgdb_conn_string: str | None = None):
        self.pgdb_conn_string = pgdb_conn_string or get_pgdb_connection()

    async def poll_events(self, event_type: Optional[str] = None, status: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        conditions: List[str] = []
        params: List[Any] = []
        if event_type:
            conditions.append("event_type = %s")
            params.append(event_type)
        if status:
            conditions.append("status = %s")
            params.append(status)
        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        sql = f"""
            SELECT 
                execution_id,
                event_id,
                parent_event_id,
                timestamp,
                event_type,
                node_id,
                node_name,
                node_type,
                status,
                duration,
                input_context,
                output_result,
                metadata,
                error
            FROM event_log
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT %s
        """
        params.append(limit)
        results: List[Dict[str, Any]] = []
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(sql, params)
                rows = await cursor.fetchall() or []
                for r in rows:
                    d = dict(r)
                    try:
                        d["input_context"] = json.loads(d["input_context"]) if d.get("input_context") else None
                        d["output_result"] = json.loads(d["output_result"]) if d.get("output_result") else None
                        d["metadata"] = json.loads(d["metadata"]) if d.get("metadata") else None
                    except Exception:
                        pass
                    results.append(d)
        return results

    async def get_all_executions(self) -> List[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT execution_id, event_id, event_type, status, timestamp
                    FROM event_log
                    ORDER BY timestamp DESC
                    LIMIT 200
                    """
                )
                return [dict(r) for r in (await cursor.fetchall() or [])]

    async def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        event_id = event_data.get("event_id", f"evt_{os.urandom(16).hex()}")
        event_type = event_data.get("event_type", "UNKNOWN")
        status = event_data.get("status", "CREATED")
        parent_event_id = event_data.get("parent_id") or event_data.get("parent_event_id")
        execution_id = event_data.get("execution_id", event_id)
        node_id = event_data.get("node_id", event_id)
        node_name = event_data.get("node_name", event_type)
        node_type = event_data.get("node_type", "event")
        duration = float(event_data.get("duration", 0.0) or 0)
        metadata = event_data.get("meta", {})
        error = event_data.get("error")
        input_context = json.dumps(event_data.get("context", {}))
        output_result = json.dumps(event_data.get("result", {}))
        metadata_str = json.dumps(metadata)

        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    "SELECT COUNT(*) FROM event_log WHERE execution_id = %s AND event_id = %s",
                    (execution_id, event_id)
                )
                row = await cursor.fetchone()
                exists = row and row[0] > 0
                if exists:
                    await cursor.execute(
                        """
                        UPDATE event_log SET
                            event_type = %s,
                            status = %s,
                            duration = %s,
                            input_context = %s,
                            output_result = %s,
                            metadata = %s,
                            error = %s,
                            timestamp = CURRENT_TIMESTAMP
                        WHERE execution_id = %s AND event_id = %s
                        """,
                        (
                            event_type,
                            status,
                            duration,
                            input_context,
                            output_result,
                            metadata_str,
                            error,
                            execution_id,
                            event_id,
                        )
                    )
                else:
                    await cursor.execute(
                        """
                        INSERT INTO event_log (
                            execution_id, event_id, parent_event_id, timestamp, event_type,
                            node_id, node_name, node_type, status, duration,
                            input_context, output_result, metadata, error
                        ) VALUES (
                            %s, %s, %s, CURRENT_TIMESTAMP, %s,
                            %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        """,
                        (
                            execution_id,
                            event_id,
                            parent_event_id,
                            event_type,
                            node_id,
                            node_name,
                            node_type,
                            status,
                            duration,
                            input_context,
                            output_result,
                            metadata_str,
                            error,
                        )
                    )
                try:
                    await conn.commit()
                except Exception:
                    pass
        return {**event_data, "event_id": event_id}

    async def get_events_by_execution_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT * FROM event_log WHERE execution_id = %s ORDER BY timestamp ASC
                    """,
                    (execution_id,)
                )
                rows = await cursor.fetchall() or []
                return {"execution_id": execution_id, "events": [dict(r) for r in rows]}

    async def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT * FROM event_log WHERE event_id = %s LIMIT 1
                    """,
                    (event_id,)
                )
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_event(self, id_param: str) -> Optional[Dict[str, Any]]:
        # Interpret id_param as event_id if exact match exists; else as execution_id
        ev = await self.get_event_by_id(id_param)
        if ev:
            return ev
        return await self.get_events_by_execution_id(id_param)


def get_catalog_service() -> CatalogService:
    return CatalogService()


def get_event_service() -> EventService:
    return EventService()


def get_catalog_service_dependency() -> CatalogService:
    return get_catalog_service()


def get_event_service_dependency() -> EventService:
    return get_event_service()


class AgentService:
    def __init__(self, pgdb_conn_string: str | None = None):
        self.pgdb_conn_string = pgdb_conn_string or get_pgdb_connection()

    async def store_transition(self, params: tuple):
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor() as cursor:
                await cursor.execute(
                    """
                    INSERT INTO execution_transition (
                        execution_id, before_state, after_state, input_payload, output_payload,
                        error, timestamp
                    ) VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    """,
                    params
                )
                try:
                    await conn.commit()
                except Exception:
                    pass

    async def get_step_results(self):
        async with get_async_db_connection(self.pgdb_conn_string) as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("SELECT * FROM execution_transition ORDER BY timestamp DESC LIMIT 100")
                return [dict(r) for r in (await cursor.fetchall() or [])]

    async def execute_agent(
        self,
        playbook_content: str,
        playbook_path: str,
        playbook_version: str,
        input_payload: Optional[Dict[str, Any]] = None,
        sync_to_postgres: bool = True,
        merge: bool = False,
    ) -> Dict[str, Any]:
        """
        Emit a REQUESTED event that the broker will
        pick up and execute. Returns scheduling info including event_id/execution_id.
        """
        execution_id = f"exec_{get_snowflake_id_str()}"
        evt = {
            "event_type": "AgentExecutionRequested",
            "status": "REQUESTED",
            "execution_id": execution_id,
            "node_type": "playbooks",
            "node_name": playbook_path,
            # 'context' -> stored as input_context in event_log
            "context": {"path": playbook_path, "version": playbook_version},
            # 'result' -> stored as output_result in event_log; broker reads as input payload
            "result": input_payload or {},
            # 'meta' -> stored as metadata in event_log
            "meta": {"resource_path": playbook_path, "resource_version": playbook_version},
        }
        es = EventService(self.pgdb_conn_string)
        saved = await es.emit(evt)
        return {
            "status": "REQUESTED",
            "event_id": saved.get("event_id"),
            "execution_id": saved.get("execution_id", execution_id),
            "playbook_path": playbook_path,
            "playbook_version": playbook_version,
            "merge": merge,
            "sync_to_postgres": sync_to_postgres,
        }


def get_agent_service() -> AgentService:
    return AgentService()


def get_agent_service_dependency() -> AgentService:
    return get_agent_service()


def get_playbook_entry_from_catalog(playbook_id: str) -> Optional[Dict[str, Any]]:
    try:
        with get_db_connection() as conn:
            with conn.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    "SELECT content FROM catalog WHERE resource_path = %s ORDER BY timestamp DESC LIMIT 1",
                    (playbook_id,)
                )
                row = cursor.fetchone()
                if row:
                    return {"content": row["content"]}
                return None
    except Exception:
        return None
