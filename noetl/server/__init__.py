# Server package public API (synchronous facades for unit tests)
from typing import Any, Dict, Optional, List
import json
import yaml
import os
from .server import (
    get_catalog_service,  # unused here, kept for __all__
    get_event_service,    # unused here, kept for __all__
    get_pgdb_connection,
    router,
    register_server_from_env,
    psycopg,
)


class CatalogService:
    """
    Synchronous implementation compatible with tests that mock noetl.server.psycopg.connect.
    API endpoints should use async services in noetl.server.server.
    """
    def __init__(self, pgdb_conn_string: Optional[str] | None = None):
        self.pgdb_conn_string = pgdb_conn_string or get_pgdb_connection()

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

    def get_latest_version(self, resource_path: str) -> str:
        try:
            conn = psycopg.connect(self.pgdb_conn_string)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM catalog WHERE resource_path = %s", (resource_path,))
            row = cur.fetchone()
            count = int(row[0]) if row else 0
            if count == 0:
                return "0.1.0"
            cur.execute("SELECT resource_version FROM catalog WHERE resource_path = %s", (resource_path,))
            versions = [r[0] for r in (cur.fetchall() or [])]
            if not versions:
                return "0.1.0"
            def _key(v: str):
                p = (v or "0").split('.')
                p += ['0'] * (3 - len(p))
                try:
                    return tuple(map(int, p[:3]))
                except Exception:
                    return (0, 0, 0)
            return max(versions, key=_key)
        except Exception:
            return "0.1.0"

    def fetch_entry(self, path: str, version: str) -> Optional[Dict[str, Any]]:
        try:
            conn = psycopg.connect(self.pgdb_conn_string)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT resource_path, resource_type, resource_version, content, payload, meta
                FROM catalog
                WHERE resource_path = %s AND resource_version = %s
                """,
                (path, version)
            )
            result = cur.fetchone()
            if not result and '/' in path:
                filename = path.split('/')[-1]
                cur.execute(
                    """
                    SELECT resource_path, resource_type, resource_version, content, payload, meta
                    FROM catalog
                    WHERE resource_path = %s AND resource_version = %s
                    """,
                    (filename, version)
                )
                result = cur.fetchone()
            if result:
                return {
                    "resource_path": result[0],
                    "resource_type": result[1],
                    "resource_version": result[2],
                    "content": result[3],
                    "payload": result[4],
                    "meta": result[5],
                }
            return None
        except Exception:
            return None

    def register_resource(self, content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
        try:
            resource_data = yaml.safe_load(content)
            resource_path = resource_data.get("path", resource_data.get("name", "unknown"))
            latest = self.get_latest_version(resource_path)
            resource_version = latest if latest == '0.1.0' else self.increment_version(latest)

            conn = psycopg.connect(self.pgdb_conn_string)
            cur = conn.cursor()
            # ensure resource type exists
            cur.execute("INSERT INTO resource (name) VALUES (%s) ON CONFLICT DO NOTHING", (resource_type,))

            # find free version (few retries)
            attempt = 0
            while attempt < 5:
                cur.execute(
                    "SELECT COUNT(*) FROM catalog WHERE resource_path = %s AND resource_version = %s",
                    (resource_path, resource_version)
                )
                row = cur.fetchone()
                if not row or int(row[0]) == 0:
                    break
                resource_version = self.increment_version(resource_version)
                attempt += 1
            if attempt >= 5:
                raise RuntimeError("Failed to find unique version")

            cur.execute(
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
                    json.dumps(resource_data),
                    json.dumps({"registered_at": "now()"}),
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
            conn = psycopg.connect(self.pgdb_conn_string)
            cur = conn.cursor()
            if resource_type:
                cur.execute(
                    """
                    SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                    FROM catalog WHERE resource_type = %s ORDER BY timestamp DESC
                    """,
                    (resource_type,)
                )
            else:
                cur.execute(
                    """
                    SELECT resource_path, resource_type, resource_version, content, payload, meta, timestamp
                    FROM catalog ORDER BY timestamp DESC
                    """
                )
            rows = cur.fetchall() or []
            entries: List[Dict[str, Any]] = []
            for r in rows:
                rp = r[0] if len(r) > 0 else None
                rt = r[1] if len(r) > 1 else None
                rv = r[2] if len(r) > 2 else None
                content = r[3] if len(r) > 3 else None
                payload = r[4] if len(r) > 4 else None
                meta = r[5] if len(r) > 5 else None
                ts = r[6] if len(r) > 6 else None
                entries.append({
                    "resource_path": rp,
                    "resource_type": rt,
                    "resource_version": rv,
                    "content": content,
                    "payload": payload,
                    "meta": meta,
                    "timestamp": ts,
                })
            return entries
        except Exception:
            return []


class EventService:
    """
    Synchronous implementation for unit tests.
    """
    def __init__(self, pgdb_conn_string: Optional[str] | None = None):
        self.pgdb_conn_string = pgdb_conn_string or get_pgdb_connection()

    def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
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

            conn = psycopg.connect(self.pgdb_conn_string)
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM event_log WHERE execution_id = %s AND event_id = %s",
                (execution_id, event_id)
            )
            exists_row = cur.fetchone()
            exists = exists_row and exists_row[0] > 0
            if exists:
                cur.execute(
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
                cur.execute(
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
                conn.commit()
            except Exception:
                pass
            return {**event_data, "event_id": event_id}
        except Exception as e:
            return {**event_data, "error": str(e)}

    def poll_events(self, event_type: Optional[str] = None, status: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        try:
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
            conn = psycopg.connect(self.pgdb_conn_string)
            cur = conn.cursor()
            cur.execute(sql, params)
            rows = cur.fetchall() or []
            results: List[Dict[str, Any]] = []
            for r in rows:
                results.append({
                    "execution_id": r[0],
                    "event_id": r[1],
                    "parent_event_id": r[2],
                    "timestamp": r[3],
                    "event_type": r[4],
                    "node_id": r[5],
                    "node_name": r[6],
                    "node_type": r[7],
                    "status": r[8],
                    "duration": r[9],
                    "input_context": json.loads(r[10]) if r[10] else None,
                    "output_result": json.loads(r[11]) if r[11] else None,
                    "metadata": json.loads(r[12]) if r[12] else None,
                    "error": r[13],
                })
            return results
        except Exception:
            return []

    # Minimal sync versions for tests
    def get_all_executions(self) -> List[Dict[str, Any]]:
        return []

    def get_events_by_execution_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        return None

    def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        return None

    def get_event(self, id_param: str) -> Optional[Dict[str, Any]]:
        return None


__all__ = [
    "CatalogService",
    "EventService",
    "get_catalog_service",
    "get_event_service",
    "get_pgdb_connection",
    "router",
    "psycopg",
]
