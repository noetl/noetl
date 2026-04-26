import asyncio
import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Annotated, Any, Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from psycopg.types.json import Json
from noetl.core.db.pool import get_pool_connection, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.core.common import convert_snowflake_ids_for_api
from noetl.server.api.event_queries import PENDING_COMMAND_COUNT_SQL
from .schema import (
    ExecutionEntryResponse,
    ExecutionDetailResponse,
    ExecutionEventResponse,
    ExecutionEventsPagination,
    CancelExecutionRequest,
    CancelExecutionResponse,
    FinalizeExecutionRequest,
    FinalizeExecutionResponse,
    CleanupStuckExecutionsRequest,
    CleanupStuckExecutionsResponse,
    AnalyzeExecutionRequest,
    AnalyzeExecutionResponse,
    AnalyzeExecutionWithAIRequest,
    AnalyzeExecutionWithAIResponse,
)

# Core engine fallback
try:
    from noetl.server.api.core import get_engine as get_core_engine
except Exception:  # pragma: no cover
    get_core_engine = None

logger = setup_logger(__name__, include_location=True)
router = APIRouter(tags=["executions"])

DEFAULT_EXECUTIONS_PAGE_SIZE = 100
MAX_EXECUTIONS_PAGE_SIZE = 200
MAX_EXECUTIONS_OFFSET = 5000


def _as_iso(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _duration_seconds(start_time: Optional[datetime], end_time: Optional[datetime]) -> Optional[float]:
    if not start_time or not end_time:
        return None
    start = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
    end = end_time if end_time.tzinfo else end_time.replace(tzinfo=timezone.utc)
    return max(0.0, (end - start).total_seconds())


def _format_duration_human(total_seconds: Optional[float]) -> Optional[str]:
    if total_seconds is None:
        return None

    seconds = max(0, int(round(float(total_seconds))))
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)

    parts: list[str] = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return " ".join(parts)


def _build_execution_event_filters(
    execution_id: str,
    *,
    since_event_id: Optional[int] = None,
    event_type: Optional[str] = None,
) -> tuple[str, dict[str, Any]]:
    where_clauses = ["execution_id = %(execution_id)s"]
    params: dict[str, Any] = {"execution_id": execution_id}

    if since_event_id is not None:
        where_clauses.append("event_id > %(since_event_id)s")
        params["since_event_id"] = since_event_id

    if event_type:
        where_clauses.append("event_type = %(event_type)s")
        params["event_type"] = event_type

    return " AND ".join(where_clauses), params


def _deserialize_event_row(row: dict[str, Any], execution_id: str) -> dict[str, Any]:
    event_data = dict(row)
    event_data["execution_id"] = execution_id
    event_data["created_at"] = _ensure_utc(row.get("created_at"))
    event_data["timestamp"] = _ensure_utc(row.get("created_at"))
    if isinstance(row.get("context"), str):
        try:
            event_data["context"] = json.loads(row["context"])
        except json.JSONDecodeError:
            pass
    if isinstance(row.get("result"), str):
        try:
            event_data["result"] = json.loads(row["result"])
        except json.JSONDecodeError:
            pass
    return event_data


async def _fetch_execution_events_page(
    cursor,
    *,
    execution_id: str,
    page: int,
    page_size: int,
    since_event_id: Optional[int],
    event_type: Optional[str],
) -> tuple[list[dict[str, Any]], dict[str, int | bool]]:
    where_sql, params = _build_execution_event_filters(
        execution_id,
        since_event_id=since_event_id,
        event_type=event_type,
    )

    await cursor.execute(
        f"""
        SELECT COUNT(*) as total
        FROM noetl.event
        WHERE {where_sql}
        """,
        params,
    )
    count_row = await cursor.fetchone()
    total_events = count_row["total"] if count_row else 0
    total_pages = (total_events + page_size - 1) // page_size if total_events > 0 else 1
    offset = (page - 1) * page_size

    params["page_size"] = page_size
    params["offset"] = offset
    await cursor.execute(
        f"""
        SELECT event_id,
               event_type,
               node_id,
               node_name,
               status,
               created_at,
               context,
               result,
               error,
               catalog_id,
               parent_execution_id,
               parent_event_id,
               duration
        FROM noetl.event
        WHERE {where_sql}
        ORDER BY event_id DESC
        LIMIT %(page_size)s OFFSET %(offset)s
        """,
        params,
    )
    rows = await cursor.fetchall()
    events = [_deserialize_event_row(row, execution_id) for row in rows]

    return events, {
        "page": page,
        "page_size": page_size,
        "total_events": total_events,
        "total_pages": total_pages,
        "has_next": page < total_pages,
        "has_prev": page > 1,
    }


async def _fetch_pending_command_counts_for_executions(
    cursor,
    execution_ids: list[str],
) -> dict[str, int]:
    if not execution_ids:
        return {}

    await cursor.execute(
        """
        WITH filtered_events AS (
            SELECT
                execution_id,
                event_type,
                meta->>'command_id' AS command_id
            FROM noetl.event
            WHERE execution_id::text IN (SELECT unnest(%s::text[]))
              AND meta ? 'command_id'
              AND event_type IN ('command.issued', 'command.completed', 'command.failed', 'command.cancelled')
        ),
        command_status AS (
            SELECT
                execution_id,
                command_id,
                MAX(CASE WHEN event_type = 'command.issued' THEN 1 ELSE 0 END) AS is_issued,
                MAX(CASE WHEN event_type IN ('command.completed', 'command.failed', 'command.cancelled') THEN 1 ELSE 0 END) AS is_terminal
            FROM filtered_events
            GROUP BY execution_id, command_id
        )
        SELECT execution_id, COUNT(*) AS pending_count
        FROM command_status
        WHERE is_issued = 1 AND is_terminal = 0
        GROUP BY execution_id
        """,
        (execution_ids,),
    )
    rows = await cursor.fetchall()
    return {str(row["execution_id"]): int(row["pending_count"] or 0) for row in rows}


def _truncate_text(value: Optional[str], max_len: int = 600) -> Optional[str]:
    if value is None:
        return None
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len] + " ...[truncated]"


def _extract_duration_ms(raw: Optional[object]) -> int:
    try:
        if raw is None:
            return 0
        value = float(raw)
        if value <= 0:
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


def _looks_like_http_activity(row: dict) -> bool:
    node_name = (row.get("node_name") or "").lower()
    if "http" in node_name:
        return True

    for field in ("context", "result", "meta"):
        value = row.get(field)
        if isinstance(value, dict):
            kind = value.get("kind")
            if isinstance(kind, str) and kind.lower() == "http":
                return True
            if isinstance(value.get("tool"), str) and value.get("tool", "").lower() == "http":
                return True
            if "url" in value or "status_code" in value:
                return True
            config = value.get("config")
            if isinstance(config, dict):
                if isinstance(config.get("kind"), str) and config.get("kind", "").lower() == "http":
                    return True
                if "url" in config or "endpoint" in config:
                    return True
    return False


def _build_cloud_context(execution_id: str, start_time: Optional[datetime], end_time: Optional[datetime]) -> dict:
    project_id = (
        os.getenv("GCP_PROJECT_ID")
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("NOETL_GCP_PROJECT_ID")
    )
    cluster_name = os.getenv("GKE_CLUSTER_NAME") or os.getenv("NOETL_GKE_CLUSTER_NAME")
    region = os.getenv("GCP_REGION") or os.getenv("GOOGLE_CLOUD_REGION") or os.getenv("NOETL_GCP_REGION")

    if not project_id:
        return {
            "configured": False,
            "message": "Set GCP_PROJECT_ID (or GOOGLE_CLOUD_PROJECT) to generate Cloud Logging/Monitoring deep links.",
        }

    query_parts = [
        'resource.type="k8s_container"',
        f'"{execution_id}"',
    ]
    if cluster_name:
        query_parts.append(f'resource.labels.cluster_name="{cluster_name}"')
    if region:
        query_parts.append(f'resource.labels.location="{region}"')

    log_query = " AND ".join(query_parts)
    encoded_query = quote(log_query, safe="")
    logs_url = f"https://console.cloud.google.com/logs/query;query={encoded_query}?project={project_id}"
    metrics_url = f"https://console.cloud.google.com/monitoring/metrics-explorer?project={project_id}"

    return {
        "configured": True,
        "project_id": project_id,
        "cluster_name": cluster_name,
        "region": region,
        "start_time": _as_iso(start_time),
        "end_time": _as_iso(end_time),
        "logs_query": log_query,
        "logs_url": logs_url,
        "metrics_url": metrics_url,
    }


def _build_ai_prompt(
    execution_id: str,
    path: str,
    status: str,
    summary: dict,
    findings: list[dict],
    recommendations: list[str],
    event_sample: list[dict],
    playbook_content: Optional[str],
    cloud_context: dict,
) -> str:
    prompt_sections = [
        "You are a senior NoETL platform engineer performing execution triage.",
        "Goal: explain root causes, bottlenecks, and concrete remediation steps.",
        "",
        f"Execution ID: {execution_id}",
        f"Playbook Path: {path}",
        f"Execution Status: {status}",
        "",
        "Summary JSON:",
        json.dumps(summary, indent=2),
        "",
        "Findings JSON:",
        json.dumps(findings, indent=2),
        "",
        "Recommendations (current heuristic):",
        json.dumps(recommendations, indent=2),
        "",
        "Cloud Context JSON:",
        json.dumps(cloud_context, indent=2),
        "",
        "Latest Event Sample JSON:",
        json.dumps(event_sample, indent=2),
    ]

    if playbook_content:
        max_chars = 60000
        content = playbook_content if len(playbook_content) <= max_chars else playbook_content[:max_chars] + "\n# ...truncated..."
        prompt_sections.extend(["", "Playbook YAML:", content])

    prompt_sections.extend([
        "",
        "Deliver output in sections:",
        "1) Executive Summary",
        "2) Primary Bottlenecks",
        "3) Failure / Risk Analysis",
        "4) Recommended DSL / runtime changes (prioritized)",
        "5) Validation plan (what to measure after fix)",
    ])
    return "\n".join(prompt_sections)


def _json_ready(value: Any) -> Any:
    """Recursively convert values to JSON-safe primitives."""
    if isinstance(value, datetime):
        return _as_iso(value)
    if isinstance(value, dict):
        return {str(k): _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    return value


def _parse_json_text(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except Exception:
            return value
    return value


def _unwrap_result_payload(value: Any) -> Any:
    """
    Unwrap common result envelopes produced by workers:
    {"kind":"data","data":...}, {"data":{"result":...}}, {"result":...}
    """
    current = _parse_json_text(value)
    max_depth = 6
    for _ in range(max_depth):
        if not isinstance(current, dict):
            return current

        if "ai_report" in current:
            return current

        if (
            current.get("kind") in {"data", "ref", "refs"}
            and "data" in current
            and isinstance(current.get("data"), (dict, list, str))
        ):
            current = _parse_json_text(current.get("data"))
            continue

        if "result" in current and isinstance(current.get("result"), (dict, list, str)):
            current = _parse_json_text(current.get("result"))
            continue

        if "data" in current and isinstance(current.get("data"), (dict, list, str)):
            current = _parse_json_text(current.get("data"))
            continue

        return current

    return current


def _extract_ai_report_from_payload(value: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_payload = _unwrap_result_payload(value)

    if isinstance(raw_payload, dict):
        if isinstance(raw_payload.get("ai_report"), dict):
            return _json_ready(raw_payload.get("ai_report")), _json_ready(raw_payload)

        report_keys = {
            "executive_summary",
            "primary_bottlenecks",
            "failure_risk_analysis",
            "recommended_dsl_runtime_changes",
            "validation_plan",
            "proposed_patch_diff",
        }
        if report_keys.intersection(raw_payload.keys()):
            return _json_ready(raw_payload), _json_ready(raw_payload)

    return {}, _json_ready(raw_payload) if isinstance(raw_payload, dict) else {}


def _derive_execution_terminal_status(row: Optional[dict[str, Any]]) -> str:
    if not row:
        return "RUNNING"

    terminal_by_type = {
        "execution.cancelled": "CANCELLED",
        "playbook.completed": "COMPLETED",
        "workflow.completed": "COMPLETED",
        "playbook.failed": "FAILED",
        "workflow.failed": "FAILED",
    }
    event_type = row.get("event_type")
    if event_type in terminal_by_type:
        return terminal_by_type[event_type]

    status = str(row.get("status") or "").upper()
    if status in {"FAILED", "CANCELLED"}:
        return status
    return "RUNNING"


_PENDING_COMMAND_COUNT_SQL = PENDING_COMMAND_COUNT_SQL


def _infer_execution_completion_from_events(
    latest_event: Optional[dict[str, Any]],
    terminal_event: Optional[dict[str, Any]],
    pending_count: int,
) -> tuple[str, Optional[datetime]]:
    terminal_event_types = {
        "execution.cancelled": "CANCELLED",
        "playbook.failed": "FAILED",
        "workflow.failed": "FAILED",
        "command.failed": "FAILED",
        "playbook.completed": "COMPLETED",
        "workflow.completed": "COMPLETED",
    }

    if terminal_event:
        return (
            terminal_event_types.get(terminal_event["event_type"], terminal_event.get("status", "RUNNING")),
            terminal_event.get("created_at"),
        )

    if latest_event and (
        latest_event.get("node_name") == "end"
        and latest_event.get("status") == "COMPLETED"
        and latest_event.get("event_type") in {"command.completed", "call.done", "step.exit"}
    ):
        return "COMPLETED", latest_event.get("created_at")

    if (
        latest_event
        and latest_event.get("event_type") == "batch.completed"
        and latest_event.get("status") == "COMPLETED"
        and pending_count <= 0
    ):
        return "COMPLETED", latest_event.get("created_at")

    return "RUNNING", None


def _execution_entry_from_row(row_dict: dict[str, Any], pending_count: int) -> ExecutionEntryResponse:
    latest_event = {
        "event_type": row_dict.get("event_type"),
        "node_name": row_dict.get("node_name"),
        "created_at": row_dict.get("end_time"),
        "status": row_dict.get("event_status") or row_dict.get("status"),
    }
    terminal_event = None
    terminal_event_type = row_dict.get("terminal_event_type")
    if terminal_event_type:
        terminal_event = {
            "event_type": terminal_event_type,
            "created_at": row_dict.get("terminal_end_time"),
            "status": row_dict.get("terminal_status"),
        }
    derived_status, inferred_end_time = _infer_execution_completion_from_events(
        latest_event,
        terminal_event,
        pending_count,
    )
    start_time = _ensure_utc(row_dict.get("start_time"))
    response_end_time = _ensure_utc(inferred_end_time) if derived_status != "RUNNING" else None
    duration_end = response_end_time or datetime.now(timezone.utc)
    duration_seconds = _duration_seconds(start_time, duration_end)
    return ExecutionEntryResponse(
        execution_id=str(row_dict["execution_id"]),
        catalog_id=str(row_dict["catalog_id"]) if row_dict.get("catalog_id") is not None else "",
        path=row_dict.get("path") or "unknown",
        version=int(row_dict.get("version") or 0),
        status=derived_status,
        start_time=start_time or datetime.now(timezone.utc),
        end_time=response_end_time,
        duration_seconds=round(duration_seconds, 3) if duration_seconds is not None else None,
        duration_human=_format_duration_human(duration_seconds),
        progress=100 if derived_status in {"COMPLETED", "FAILED", "CANCELLED"} else 0,
        result=row_dict.get("result"),
        error=row_dict.get("error"),
        parent_execution_id=str(row_dict["parent_execution_id"]) if row_dict.get("parent_execution_id") is not None else None,
    )


def _default_validation_commands(path: str, version: Any) -> tuple[list[str], list[str]]:
    version_suffix = f"@{version}" if version not in (None, "", "latest") else ""
    catalog_ref = f"catalog://{path}{version_suffix}" if path else "catalog://<playbook-path>"
    dry_run_commands = [
        f"noetl exec {catalog_ref} -r distributed --dry-run",
    ]
    test_commands = [
        "pytest -q",
    ]
    return dry_run_commands, test_commands


async def _load_db_rows_for_ai(
    execution_id: int,
    include_event_rows: bool,
    event_rows_limit: int,
    include_event_log_rows: bool,
    event_log_rows_limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    event_rows: list[dict[str, Any]] = []
    event_log_rows: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []

    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            if include_event_rows:
                await cursor.execute(
                    """
                    SELECT
                      event_id,
                      event_type,
                      node_name,
                      status,
                      created_at,
                      duration,
                      CASE WHEN context IS NULL THEN NULL ELSE LEFT(context::text, 4000) END AS context,
                      CASE WHEN result IS NULL THEN NULL ELSE LEFT(result::text, 4000) END AS result,
                      error,
                      CASE WHEN meta IS NULL THEN NULL ELSE LEFT(meta::text, 2000) END AS meta
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id DESC
                    LIMIT %s
                    """,
                    (execution_id, event_rows_limit),
                )
                rows = await cursor.fetchall()
                event_rows = [_json_ready(dict(r)) for r in rows]

            if include_event_log_rows:
                await cursor.execute(
                    "SELECT to_regclass('noetl.event_log') AS regclass_name"
                )
                reg_row = await cursor.fetchone()
                if reg_row and reg_row.get("regclass_name"):
                    await cursor.execute(
                        """
                        SELECT
                          event_id,
                          event_type,
                          node_name,
                          status,
                          created_at,
                          duration,
                          CASE WHEN context IS NULL THEN NULL ELSE LEFT(context::text, 4000) END AS context,
                          CASE WHEN result IS NULL THEN NULL ELSE LEFT(result::text, 4000) END AS result,
                          error,
                          CASE WHEN meta IS NULL THEN NULL ELSE LEFT(meta::text, 2000) END AS meta
                        FROM noetl.event_log
                        WHERE execution_id = %s
                        ORDER BY event_id DESC
                        LIMIT %s
                        """,
                        (execution_id, event_log_rows_limit),
                    )
                    rows = await cursor.fetchall()
                    event_log_rows = [_json_ready(dict(r)) for r in rows]

    try:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT to_regclass('noetl.metric') AS regclass_name"
                )
                metric_reg = await cursor.fetchone()
                if metric_reg and metric_reg.get("regclass_name"):
                    await cursor.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema = 'noetl' AND table_name = 'metric'
                        """
                    )
                    cols = {row["column_name"] for row in (await cursor.fetchall())}

                    where_clauses = []
                    params: list[Any] = []
                    if "labels" in cols:
                        where_clauses.append("(labels->>'execution_id' = %s OR labels->>'parent_execution_id' = %s)")
                        params.extend([str(execution_id), str(execution_id)])
                    if "execution_id" in cols:
                        where_clauses.append("execution_id = %s")
                        params.append(execution_id)

                    if where_clauses:
                        ts_column = "created_at" if "created_at" in cols else "timestamp" if "timestamp" in cols else None
                        order_sql = f"ORDER BY {ts_column} DESC" if ts_column else ""
                        sql = (
                            "SELECT * FROM noetl.metric "
                            f"WHERE {' OR '.join(where_clauses)} "
                            f"{order_sql} LIMIT 80"
                        )
                        await cursor.execute(sql, tuple(params))
                        rows = await cursor.fetchall()
                        metric_rows = [_json_ready(dict(r)) for r in rows]
    except Exception as metric_exc:
        logger.warning("Skipping metric rows for execution %s due to query error: %s", execution_id, metric_exc)

    return event_rows, event_log_rows, metric_rows


async def _wait_for_terminal_event(
    execution_id: int,
    timeout_seconds: int,
    poll_interval_ms: int,
) -> tuple[Optional[dict[str, Any]], bool]:
    terminal_events = {
        "execution.cancelled",
        "playbook.completed",
        "playbook.failed",
        "workflow.completed",
        "workflow.failed",
    }
    deadline = time.monotonic() + timeout_seconds
    last_row: Optional[dict[str, Any]] = None

    while time.monotonic() < deadline:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    """
                    SELECT event_id, event_type, status, created_at, node_name, error
                    FROM noetl.event
                    WHERE execution_id = %s
                      AND event_type IN (
                        'execution.cancelled',
                        'playbook.completed',
                        'playbook.failed',
                        'workflow.completed',
                        'workflow.failed'
                      )
                    ORDER BY event_id DESC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                terminal_row = await cursor.fetchone()
                if terminal_row:
                    return _json_ready(dict(terminal_row)), False

                await cursor.execute(
                    """
                    SELECT event_id, event_type, status, created_at, node_name, error
                    FROM noetl.event
                    WHERE execution_id = %s
                    ORDER BY event_id DESC
                    LIMIT 1
                    """,
                    (execution_id,),
                )
                row = await cursor.fetchone()
                if row:
                    last_row = dict(row)
                    if row.get("event_type") in terminal_events:
                        return _json_ready(last_row), False

        await asyncio.sleep(max(0.2, poll_interval_ms / 1000.0))

    return _json_ready(last_row) if last_row else None, True


async def _load_ai_execution_output(
    ai_execution_id: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """
                SELECT event_type, status, created_at, error
                FROM noetl.event
                WHERE execution_id = %s
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (ai_execution_id,),
            )
            latest_row = await cursor.fetchone()

            await cursor.execute(
                """
                SELECT
                  event_id,
                  event_type,
                  node_name,
                  status,
                  created_at,
                  result,
                  error
                FROM noetl.event
                WHERE execution_id = %s
                ORDER BY event_id DESC
                LIMIT 500
                """,
                (ai_execution_id,),
            )
            rows = await cursor.fetchall()

    ai_report: dict[str, Any] = {}
    ai_raw_output: dict[str, Any] = {}
    for row in rows:
        parsed_report, parsed_raw = _extract_ai_report_from_payload(row.get("result"))
        if parsed_report:
            ai_report = parsed_report
            ai_raw_output = parsed_raw
            break

    if not ai_raw_output and rows:
        first_row = rows[0]
        ai_raw_output = {
            "node_name": first_row.get("node_name"),
            "event_type": first_row.get("event_type"),
            "status": first_row.get("status"),
            "error": _truncate_text(first_row.get("error"), 1200),
            "result": _json_ready(_unwrap_result_payload(first_row.get("result"))),
        }

    status = _derive_execution_terminal_status(dict(latest_row) if latest_row else None)
    return ai_report, ai_raw_output, status


@router.post("/executions/{execution_id}/finalize", response_model=FinalizeExecutionResponse)
async def finalize_execution(execution_id: str, request: FinalizeExecutionRequest = Body(default=None)):
    """
    Forcibly finalize an execution by emitting terminal events if not already completed.
    This is for admin/automation use to close out stuck or abandoned executions.
    """
    if get_core_engine is None:
        raise HTTPException(status_code=500, detail="Execution engine not available")
    engine = get_core_engine()
    # Try to load state
    state = await engine.state_store.load_state(execution_id)
    if not state:
        return FinalizeExecutionResponse(
            status="not_found",
            execution_id=execution_id,
            message=f"Execution {execution_id} not found in engine state store"
        )
    if state.completed:
        return FinalizeExecutionResponse(
            status="already_completed",
            execution_id=execution_id,
            message=f"Execution {execution_id} is already completed"
        )
    reason = request.reason if request and request.reason else "Abandoned or timed out"
    await engine.finalize_abandoned_execution(execution_id, reason=reason)
    return FinalizeExecutionResponse(
        status="finalized",
        execution_id=execution_id,
        message=f"Emitted terminal events for execution {execution_id}"
    )


@router.get("/executions", response_model=list[ExecutionEntryResponse])
async def get_executions(
    page: int = 1,
    page_size: int = DEFAULT_EXECUTIONS_PAGE_SIZE,
):
    """
    List executions in a paginated fashion.

    Results are ordered from most recent to oldest and limited by the `page` and
    `page_size` query parameters. The requested `page_size` is capped by a
    server-side maximum, so clients must paginate to traverse the full result set.
    """
    page = max(1, int(page))
    page_size = max(1, min(MAX_EXECUTIONS_PAGE_SIZE, int(page_size)))
    offset = (page - 1) * page_size
    if offset > MAX_EXECUTIONS_OFFSET:
        raise HTTPException(
            status_code=422,
            detail=f"Requested page is too deep. Max supported offset is {MAX_EXECUTIONS_OFFSET}.",
        )
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            try:
                # Keep this endpoint lightweight for UI polling. Avoid scanning giant payload columns.
                await cursor.execute("SET LOCAL statement_timeout = '8s'")
                await cursor.execute("""
                    WITH latest AS (
                        SELECT DISTINCT ON (execution_id)
                            execution_id, event_type, node_name, status AS event_status,
                            created_at, catalog_id, parent_execution_id, error
                        FROM noetl.event
                        WHERE execution_id IS NOT NULL
                        ORDER BY execution_id, event_id DESC
                    ),
                    first_event AS (
                        SELECT DISTINCT ON (execution_id)
                            execution_id, created_at AS first_created_at, catalog_id AS first_catalog_id,
                            parent_execution_id AS first_parent_execution_id
                        FROM noetl.event
                        WHERE execution_id IS NOT NULL
                        ORDER BY execution_id, event_id ASC
                    ),
                    terminal AS (
                        SELECT DISTINCT ON (execution_id)
                            execution_id, event_type, status, created_at, error
                        FROM noetl.event
                        WHERE execution_id IS NOT NULL
                          AND event_type IN (
                            'execution.cancelled',
                            'playbook.failed',
                            'workflow.failed',
                            'command.failed',
                            'playbook.completed',
                            'workflow.completed'
                          )
                        ORDER BY execution_id, event_id DESC
                    )
                    SELECT
                        l.execution_id,
                        COALESCE(e.catalog_id, l.catalog_id, f.first_catalog_id) AS catalog_id,
                        l.event_type,
                        l.node_name,
                        COALESCE(e.status, l.event_status) AS status,
                        l.event_status,
                        l.event_type AS derived_event_type,
                        COALESCE(e.start_time, f.first_created_at) AS start_time,
                        COALESCE(e.end_time, l.created_at) AS end_time,
                        NULL::jsonb AS result,
                        COALESCE(e.error, t.error, l.error) AS error,
                        COALESCE(e.parent_execution_id, l.parent_execution_id, f.first_parent_execution_id) AS parent_execution_id,
                        t.event_type AS terminal_event_type,
                        t.status AS terminal_status,
                        t.created_at AS terminal_end_time,
                        COALESCE(c.path, 'unknown') AS path,
                        COALESCE(c.version, 0) AS version
                    FROM latest l
                    JOIN first_event f ON f.execution_id = l.execution_id
                    LEFT JOIN terminal t ON t.execution_id = l.execution_id
                    LEFT JOIN noetl.execution e ON e.execution_id = l.execution_id
                    LEFT JOIN noetl.catalog c ON c.catalog_id = COALESCE(e.catalog_id, l.catalog_id, f.first_catalog_id)
                    ORDER BY COALESCE(e.start_time, f.first_created_at) DESC NULLS LAST, l.execution_id DESC
                    LIMIT %(limit)s
                    OFFSET %(offset)s
                """, {"limit": page_size, "offset": offset})
                rows = await cursor.fetchall()
                candidate_execution_ids = [
                    str(row["execution_id"])
                    for row in rows
                    if row.get("derived_event_type") == "batch.completed"
                    and str(row.get("event_status") or "").upper() == "COMPLETED"
                    and row.get("terminal_event_type") is None
                ]
                pending_counts = await _fetch_pending_command_counts_for_executions(
                    cursor,
                    candidate_execution_ids,
                )
            except Exception as exc:
                logger.error("Failed to load executions list: %s", exc)
                raise HTTPException(
                    status_code=503,
                    detail="Execution list query timed out or DB pool is busy. Retry in a few seconds.",
                ) from exc
            resp = []
            for row_dict in rows:
                pending_count = pending_counts.get(str(row_dict["execution_id"]), 0)
                resp.append(_execution_entry_from_row(row_dict, pending_count))
            return resp


@router.post("/executions/{execution_id}/cancel", response_model=CancelExecutionResponse)
async def cancel_execution(execution_id: str, request: CancelExecutionRequest = None):
    """
    Cancel a running execution.
    
    Emits execution.cancelled events to stop workers from processing further commands.
    If cascade=True (default), also cancels all child executions (sub-playbooks).
    
    **Request Body (optional)**:
    ```json
    {
        "reason": "User requested cancellation",
        "cascade": true
    }
    ```
    
    **Response**:
    ```json
    {
        "status": "cancelled",
        "execution_id": "123456789",
        "cancelled_executions": ["123456789", "987654321"],
        "message": "Cancelled 2 executions"
    }
    ```
    """
    if request is None:
        request = CancelExecutionRequest()
    
    cancelled_ids = []
    
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Check if execution exists and get its current state
            await cur.execute("""
                SELECT e.execution_id, e.status, e.event_type, e.catalog_id
                FROM noetl.event e
                WHERE e.execution_id = %s
                ORDER BY e.event_id DESC
                LIMIT 1
            """, (int(execution_id),))
            latest_event = await cur.fetchone()
            
            if not latest_event:
                raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
            
            # Only terminal lifecycle events should mark an execution terminal.
            # command.completed/status=COMPLETED does not mean workflow completion.
            terminal_event_types = {
                'playbook.completed',
                'workflow.completed',
                'playbook.failed',
                'workflow.failed',
                'command.failed',
                'execution.cancelled',
            }

            if latest_event['event_type'] in terminal_event_types:
                return CancelExecutionResponse(
                    status="already_completed",
                    execution_id=execution_id,
                    cancelled_executions=[],
                    message=f"Execution {execution_id} is already {latest_event['status']}"
                )
            
            # Collect all execution IDs to cancel (parent + children if cascade)
            execution_ids_to_cancel = [int(execution_id)]
            
            if request.cascade:
                # Find all child executions recursively
                await cur.execute("""
                    WITH RECURSIVE children AS (
                        SELECT DISTINCT execution_id 
                        FROM noetl.event 
                        WHERE parent_execution_id = %s
                        UNION
                        SELECT DISTINCT e.execution_id 
                        FROM noetl.event e
                        INNER JOIN children c ON e.parent_execution_id = c.execution_id
                    )
                    SELECT execution_id FROM children
                """, (int(execution_id),))
                children = await cur.fetchall()
                execution_ids_to_cancel.extend([row['execution_id'] for row in children])
            
            # Emit execution.cancelled event for each execution
            now = datetime.now(timezone.utc)
            for exec_id in execution_ids_to_cancel:
                event_id = await get_snowflake_id()
                
                # Get catalog_id for this execution
                await cur.execute("""
                    SELECT catalog_id FROM noetl.event 
                    WHERE execution_id = %s AND catalog_id IS NOT NULL
                    LIMIT 1
                """, (exec_id,))
                cat_row = await cur.fetchone()
                catalog_id = cat_row['catalog_id'] if cat_row else latest_event['catalog_id']
                
                meta = {
                    "reason": request.reason,
                    "cancelled_by": "api",
                    "cascade": request.cascade,
                    "parent_cancel_id": execution_id if exec_id != int(execution_id) else None,
                    "actionable": True,
                }
                
                await cur.execute("""
                    INSERT INTO noetl.event (
                        event_id, execution_id, catalog_id, event_type,
                        node_id, node_name, status, meta, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (
                    event_id, exec_id, catalog_id, "execution.cancelled",
                    "cancel", "cancel", "CANCELLED",
                    Json(meta), now
                ))
                
                cancelled_ids.append(str(exec_id))
                logger.info(f"Cancelled execution {exec_id} - reason: {request.reason}")
            
            await conn.commit()
    
    return CancelExecutionResponse(
        status="cancelled",
        execution_id=execution_id,
        cancelled_executions=cancelled_ids,
        message=f"Cancelled {len(cancelled_ids)} execution(s)"
    )


@router.get("/executions/{execution_id}/cancellation-check", response_class=JSONResponse)
async def get_execution_cancellation_status(execution_id: str):
    """
    Get quick execution status including cancellation state.
    
    Lightweight endpoint for workers to check if execution is cancelled.
    
    **Response**:
    ```json
    {
        "execution_id": "123456789",
        "status": "RUNNING",
        "cancelled": false,
        "completed": false,
        "failed": false
    }
    ```
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            # Get latest event status
            await cur.execute("""
                SELECT event_type, status
                FROM noetl.event
                WHERE execution_id = %s
                ORDER BY event_id DESC
                LIMIT 1
            """, (int(execution_id),))
            latest = await cur.fetchone()
            
            if not latest:
                raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")
            
            # Check for cancellation event
            await cur.execute("""
                SELECT 1 FROM noetl.event
                WHERE execution_id = %s AND event_type = 'execution.cancelled'
                LIMIT 1
            """, (int(execution_id),))
            cancelled = await cur.fetchone() is not None
            
            terminal_status_by_event = {
                "execution.cancelled": "CANCELLED",
                "playbook.completed": "COMPLETED",
                "workflow.completed": "COMPLETED",
                "playbook.failed": "FAILED",
                "workflow.failed": "FAILED",
                "command.failed": "FAILED",
            }
            completed_events = {'playbook.completed', 'workflow.completed'}
            failed_events = {'playbook.failed', 'workflow.failed', 'command.failed'}

            derived_status = terminal_status_by_event.get(latest["event_type"])
            if derived_status is None:
                derived_status = "CANCELLED" if cancelled else "RUNNING"

            return {
                "execution_id": execution_id,
                "status": derived_status,
                "event_type": latest['event_type'],
                "cancelled": cancelled,
                "completed": latest['event_type'] in completed_events,
                "failed": latest['event_type'] in failed_events
            }


@router.get("/executions/{execution_id}", response_model=ExecutionDetailResponse)
async def get_execution(
    execution_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=100, ge=10, le=500, description="Events per page"),
    since_event_id: Optional[int] = Query(default=None, description="Get events after this event_id (for incremental loading)"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type"),
    include_events: Annotated[bool, Query(description="Include paginated events in the response")] = True,
):
    """
    Get execution by ID with paginated event history.

    **Query Parameters**:
    - `page`: Page number (default: 1)
    - `page_size`: Events per page (default: 100, max: 500)
    - `since_event_id`: Get only events after this ID (for incremental polling)
    - `event_type`: Filter events by type

    **Response includes pagination metadata**:
    ```json
    {
        "execution_id": "...",
        "events": [...],
        "pagination": {
            "page": 1,
            "page_size": 100,
            "total_events": 5000,
            "total_pages": 50,
            "has_next": true,
            "has_prev": false
        }
    }
    ```
    """
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            events: list[dict[str, Any]] = []
            pagination = {
                "page": page,
                "page_size": page_size,
                "total_events": 0,
                "total_pages": 1,
                "has_next": False,
                "has_prev": False,
            }
            if include_events:
                events, pagination = await _fetch_execution_events_page(
                    cursor,
                    execution_id=execution_id,
                    page=page,
                    page_size=page_size,
                    since_event_id=since_event_id,
                    event_type=event_type,
                )

            # Also get execution metadata (first event info) in a separate efficient query
            await cursor.execute("""
                SELECT event_id, event_type, catalog_id, parent_execution_id, created_at, status
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                ORDER BY event_id ASC
                LIMIT 1
            """, {"execution_id": execution_id})
            first_event = await cursor.fetchone()

            # Get terminal status efficiently
            await cursor.execute("""
                SELECT event_type, status, created_at, error
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                  AND event_type IN ('execution.cancelled', 'playbook.failed', 'workflow.failed',
                                     'command.failed', 'playbook.completed', 'workflow.completed')
                ORDER BY event_id DESC
                LIMIT 1
            """, {"execution_id": execution_id})
            terminal_event = await cursor.fetchone()

            # Get latest event for end_time and fallback completion inference
            await cursor.execute("""
                SELECT event_type, node_name, created_at, status, error
                FROM noetl.event
                WHERE execution_id = %(execution_id)s
                ORDER BY event_id DESC
                LIMIT 1
            """, {"execution_id": execution_id})
            latest_event = await cursor.fetchone()

            pending_row = {"pending_count": 0}
            should_check_pending_commands = (
                terminal_event is None
                and latest_event is not None
                and latest_event.get("event_type") == "batch.completed"
                and latest_event.get("status") == "COMPLETED"
            )
            if should_check_pending_commands:
                await cursor.execute(
                    _PENDING_COMMAND_COUNT_SQL,
                    {"execution_id": execution_id},
                )
                pending_row = await cursor.fetchone()

    if first_event is None:
        # No events found - check engine fallback
        if get_core_engine:
            try:
                engine = get_core_engine()
                state = engine.state_store.get_state(execution_id)
                if state:
                    path = None
                    if state.playbook and getattr(state.playbook, "metadata", None):
                        path = state.playbook.metadata.get("path") or state.playbook.metadata.get("name")
                    status = "FAILED" if state.failed else "COMPLETED" if state.completed else "RUNNING"
                    return ExecutionDetailResponse(
                        execution_id=execution_id,
                        catalog_id=str(state.catalog_id) if state.catalog_id is not None else "",
                        path=path or "unknown",
                        version=0,
                        status=status,
                        start_time=datetime.now(timezone.utc),
                        end_time=None,
                        duration_seconds=None,
                        duration_human=None,
                        progress=100 if status in {"COMPLETED", "FAILED", "CANCELLED"} else 0,
                        result=None,
                        error=None,
                        parent_execution_id=str(state.parent_execution_id) if state.parent_execution_id is not None else None,
                        events=[ExecutionEventResponse(**event) for event in events] if include_events else [],
                        events_included=include_events,
                        events_endpoint=f"/api/executions/{execution_id}/events",
                        pagination=ExecutionEventsPagination(**pagination) if include_events else None,
                    )
            except Exception as e:
                logger.warning(f"Execution engine fallback failed for execution {execution_id}: {e}")
        raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

    # Get playbook path and version from catalog
    playbook_path = "unknown"
    playbook_version = None
    catalog_id = first_event.get("catalog_id")
    if catalog_id:
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT path, version FROM noetl.catalog WHERE catalog_id = %s
                """, (catalog_id,))
                catalog_row = await cursor.fetchone()
        if catalog_row:
            playbook_path = catalog_row["path"]
            playbook_version = catalog_row["version"]

    pending_count = int((pending_row or {}).get("pending_count", 0))
    final_status, inferred_end_time = _infer_execution_completion_from_events(
        dict(latest_event) if latest_event else None,
        dict(terminal_event) if terminal_event else None,
        pending_count,
    )

    start_time = _ensure_utc(first_event.get("created_at")) if first_event else None
    end_time = _ensure_utc(inferred_end_time)
    duration_end = end_time or datetime.now(timezone.utc)
    duration_seconds = _duration_seconds(start_time, duration_end)

    return ExecutionDetailResponse(
        execution_id=execution_id,
        path=playbook_path,
        catalog_id=str(catalog_id) if catalog_id else "",
        version=int(playbook_version or 0),
        status=final_status,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=round(duration_seconds, 3) if duration_seconds is not None else None,
        duration_human=_format_duration_human(duration_seconds),
        progress=100 if final_status in {"COMPLETED", "FAILED", "CANCELLED"} else 0,
        result=None,
        error=(
            terminal_event.get("error")
            if terminal_event and terminal_event.get("error") is not None
            else latest_event.get("error") if latest_event else None
        ),
        parent_execution_id=str(first_event["parent_execution_id"]) if first_event.get("parent_execution_id") is not None else None,
        events=[ExecutionEventResponse(**event) for event in events] if include_events else [],
        events_included=include_events,
        events_endpoint=f"/api/executions/{execution_id}/events",
        pagination=ExecutionEventsPagination(**pagination) if include_events else None,
    )


@router.get("/executions/{execution_id}/events", response_class=JSONResponse)
async def get_execution_events(
    execution_id: str,
    page: int = Query(default=1, ge=1, description="Page number (1-indexed)"),
    page_size: int = Query(default=100, ge=10, le=500, description="Events per page"),
    since_event_id: Optional[int] = Query(default=None, description="Get events after this event_id (for incremental loading)"),
    event_type: Optional[str] = Query(default=None, description="Filter by event type"),
):
    detail = await get_execution(
        execution_id=execution_id,
        page=1,
        page_size=1,
        since_event_id=None,
        event_type=None,
        include_events=False,
    )
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            events, pagination = await _fetch_execution_events_page(
                cursor,
                execution_id=execution_id,
                page=page,
                page_size=page_size,
                since_event_id=since_event_id,
                event_type=event_type,
            )
    return {
        "execution_id": detail.execution_id,
        "path": detail.path,
        "status": detail.status,
        "events": events,
        "pagination": pagination,
    }


@router.post("/executions/{execution_id}/analyze", response_model=AnalyzeExecutionResponse)
async def analyze_execution(
    execution_id: str,
    request: AnalyzeExecutionRequest = Body(default=None),
):
    """
    Build an AI-ready execution analysis bundle.

    The bundle combines execution events, playbook YAML, and cloud deep links
    so users can paste one payload into any LLM and get actionable diagnostics.
    """
    request = request or AnalyzeExecutionRequest()

    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """
                SELECT
                  e.catalog_id,
                  c.path,
                  c.version
                FROM noetl.event e
                LEFT JOIN noetl.catalog c ON c.catalog_id = e.catalog_id
                WHERE e.execution_id = %s
                ORDER BY e.event_id ASC
                LIMIT 1
                """,
                (int(execution_id),),
            )
            base_row = await cursor.fetchone()
            if not base_row:
                raise HTTPException(status_code=404, detail=f"Execution {execution_id} not found")

            await cursor.execute(
                """
                SELECT event_type, status, created_at
                FROM noetl.event
                WHERE execution_id = %s
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (int(execution_id),),
            )
            latest_row = await cursor.fetchone()

            await cursor.execute(
                """
                SELECT event_type, status, created_at
                FROM noetl.event
                WHERE execution_id = %s
                  AND event_type IN (
                    'execution.cancelled',
                    'playbook.failed',
                    'workflow.failed',
                    'playbook.completed',
                    'workflow.completed'
                  )
                ORDER BY event_id DESC
                LIMIT 1
                """,
                (int(execution_id),),
            )
            terminal_row = await cursor.fetchone()

            await cursor.execute(
                """
                SELECT
                  event_id,
                  event_type,
                  node_name,
                  status,
                  created_at,
                  duration,
                  error
                FROM noetl.event
                WHERE execution_id = %s
                ORDER BY event_id ASC
                LIMIT %s
                """,
                (int(execution_id), request.max_events),
            )
            event_rows = await cursor.fetchall()

            playbook_content = None
            if request.include_playbook_content and base_row.get("catalog_id"):
                await cursor.execute(
                    """
                    SELECT content
                    FROM noetl.catalog
                    WHERE catalog_id = %s
                    """,
                    (base_row["catalog_id"],),
                )
                catalog_content_row = await cursor.fetchone()
                if catalog_content_row:
                    playbook_content = catalog_content_row.get("content")

    if not event_rows:
        raise HTTPException(status_code=404, detail=f"No events found for execution {execution_id}")

    first_event_time = event_rows[0].get("created_at")
    last_event_time = (latest_row or {}).get("created_at")
    duration_seconds = 0.0
    if first_event_time and last_event_time:
        duration_seconds = max(0.0, (last_event_time - first_event_time).total_seconds())

    path = base_row.get("path") or "unknown"
    status = (
        (terminal_row or {}).get("status")
        or (latest_row or {}).get("status")
        or "UNKNOWN"
    )

    event_type_counts = Counter()
    status_counts = Counter()
    node_event_counts = Counter()
    command_issued_by_node = Counter()
    node_duration_totals_ms = defaultdict(int)
    node_duration_samples = defaultdict(int)
    failed_events = 0
    http_activity_events = 0

    for row in event_rows:
        event_type = row.get("event_type") or "UNKNOWN"
        node_name = row.get("node_name") or "UNKNOWN"
        row_status = row.get("status") or "UNKNOWN"
        duration_ms = _extract_duration_ms(row.get("duration"))

        event_type_counts[event_type] += 1
        status_counts[row_status] += 1
        node_event_counts[node_name] += 1

        if event_type == "command.issued":
            command_issued_by_node[node_name] += 1

        if duration_ms > 0:
            node_duration_totals_ms[node_name] += duration_ms
            node_duration_samples[node_name] += 1

        if "failed" in event_type.lower() or str(row_status).upper() == "FAILED":
            failed_events += 1

        if _looks_like_http_activity(row):
            http_activity_events += 1

    retry_nodes = {
        node: count - 1
        for node, count in command_issued_by_node.items()
        if count > 1
    }
    retry_attempts = sum(retry_nodes.values())

    slowest_nodes = []
    for node, total_ms in node_duration_totals_ms.items():
        samples = node_duration_samples.get(node, 0)
        if samples <= 0:
            continue
        slowest_nodes.append(
            {
                "node_name": node,
                "total_duration_ms": total_ms,
                "avg_duration_ms": round(total_ms / samples, 2),
                "samples": samples,
            }
        )
    slowest_nodes.sort(key=lambda item: item["total_duration_ms"], reverse=True)
    slowest_nodes = slowest_nodes[:8]

    total_step_duration_ms = sum(item["total_duration_ms"] for item in slowest_nodes)
    dominant_node = slowest_nodes[0] if slowest_nodes else None
    dominant_share = (
        (dominant_node["total_duration_ms"] / total_step_duration_ms)
        if dominant_node and total_step_duration_ms > 0
        else 0.0
    )

    findings: list[dict] = []
    recommendations: list[str] = []

    if duration_seconds >= 60:
        findings.append(
            {
                "severity": "high",
                "title": "High Execution Duration",
                "detail": f"Execution took {round(duration_seconds, 2)} seconds.",
                "evidence": {
                    "duration_seconds": round(duration_seconds, 2),
                    "event_count": len(event_rows),
                },
            }
        )
        recommendations.append("Reduce per-item network latency: avoid high-latency external endpoints for row-wise enrichment.")

    if dominant_node and dominant_share >= 0.65:
        findings.append(
            {
                "severity": "medium",
                "title": "Single Step Dominates Runtime",
                "detail": (
                    f"Node '{dominant_node['node_name']}' consumes "
                    f"{round(dominant_share * 100, 1)}% of measured step duration."
                ),
                "evidence": dominant_node,
            }
        )
        recommendations.append(
            "Split dominant task_sequence into smaller distributed steps or add bounded parallel fan-out for HTTP-heavy loops."
        )

    if retry_attempts > 0:
        findings.append(
            {
                "severity": "medium",
                "title": "Retries Detected",
                "detail": f"Detected {retry_attempts} retry attempts across {len(retry_nodes)} nodes.",
                "evidence": {"retry_nodes": retry_nodes},
            }
        )
        recommendations.append("Inspect retryable failures and adjust timeouts/backoff to reduce repeated attempts.")

    if failed_events > 0:
        findings.append(
            {
                "severity": "high",
                "title": "Failure Events Present",
                "detail": f"Detected {failed_events} failed/error events in execution timeline.",
                "evidence": {"failed_events": failed_events},
            }
        )
        recommendations.append("Review the first failure event and add explicit error-branch handling in DSL policy rules.")

    terminal_event_type = (terminal_row or {}).get("event_type")
    if terminal_event_type is None:
        findings.append(
            {
                "severity": "medium",
                "title": "Missing Terminal Lifecycle Event",
                "detail": "No playbook/workflow terminal event found in current event window.",
                "evidence": {"latest_event_type": (latest_row or {}).get("event_type")},
            }
        )
        recommendations.append("Ensure terminal events are emitted consistently to avoid stale RUNNING states in UI.")

    if http_activity_events > 0:
        recommendations.append(
            "For high-volume HTTP enrichment, prefer in-cluster low-latency endpoints and connection reuse."
        )

    if not recommendations:
        recommendations.append("No major issues detected from current event sample.")

    summary = {
        "event_count": len(event_rows),
        "duration_seconds": round(duration_seconds, 3),
        "status_counts": dict(status_counts),
        "event_type_counts": dict(event_type_counts),
        "failed_event_count": failed_events,
        "http_activity_event_count": http_activity_events,
        "retry_attempts": retry_attempts,
        "retry_nodes": retry_nodes,
        "top_nodes_by_events": node_event_counts.most_common(10),
        "slowest_nodes": slowest_nodes,
        "terminal_event_type": terminal_event_type,
    }

    sample_count = min(request.event_sample_size, len(event_rows))
    latest_events = event_rows[-sample_count:]
    event_sample = [
        {
            "event_id": str(row.get("event_id")),
            "event_type": row.get("event_type"),
            "node_name": row.get("node_name"),
            "status": row.get("status"),
            "timestamp": _as_iso(row.get("created_at")),
            "duration_ms": _extract_duration_ms(row.get("duration")),
            "error": _truncate_text(row.get("error"), max_len=400),
        }
        for row in latest_events
    ]

    cloud = _build_cloud_context(execution_id, first_event_time, last_event_time)
    ai_prompt = _build_ai_prompt(
        execution_id=execution_id,
        path=path,
        status=status,
        summary=summary,
        findings=findings,
        recommendations=recommendations,
        event_sample=event_sample,
        playbook_content=playbook_content,
        cloud_context=cloud,
    )

    return AnalyzeExecutionResponse(
        execution_id=str(execution_id),
        path=path,
        status=status,
        generated_at=datetime.now(timezone.utc),
        summary=summary,
        findings=findings,
        recommendations=recommendations,
        cloud=cloud,
        playbook={
            "catalog_id": str(base_row.get("catalog_id")) if base_row.get("catalog_id") else None,
            "path": path,
            "version": base_row.get("version"),
            "content": playbook_content if request.include_playbook_content else None,
        },
        event_sample=event_sample,
        ai_prompt=ai_prompt,
    )


@router.post("/executions/{execution_id}/analyze/ai", response_model=AnalyzeExecutionWithAIResponse)
async def analyze_execution_with_ai(
    execution_id: str,
    request: AnalyzeExecutionWithAIRequest = Body(default=None),
):
    """
    Run execution triage through AI analyzer playbook and return structured report.

    Human-in-the-loop safeguards:
    - `auto_fix_mode=apply` requires `approved=true` when `approval_required=true`
    - analyzer returns patch proposal + dry-run/test commands (no direct code apply)
    """
    request = request or AnalyzeExecutionWithAIRequest()
    auto_fix_mode = (request.auto_fix_mode or "report").strip().lower()
    valid_modes = {"report", "dry_run", "apply"}

    if auto_fix_mode not in valid_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid auto_fix_mode '{request.auto_fix_mode}'. Expected one of: {sorted(valid_modes)}",
        )

    if auto_fix_mode == "apply" and request.approval_required and not request.approved:
        raise HTTPException(
            status_code=400,
            detail="Apply mode requires approved=true when approval_required=true",
        )

    try:
        execution_id_int = int(execution_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid execution_id '{execution_id}'") from exc

    # Apply server-side safety caps to avoid oversized AI payloads and OOM.
    safe_max_events = max(100, min(int(request.max_events), 2000))
    safe_event_sample_size = max(20, min(int(request.event_sample_size), 200))
    safe_event_rows_limit = max(50, min(int(request.event_rows_limit), 200))
    safe_event_log_rows_limit = max(20, min(int(request.event_log_rows_limit), 80))

    # Build base bundle first (same output as "Analyze Execution" flow).
    bundle_req = AnalyzeExecutionRequest(
        max_events=safe_max_events,
        event_sample_size=safe_event_sample_size,
        include_playbook_content=request.include_playbook_content,
    )
    bundle = await analyze_execution(execution_id=execution_id, request=bundle_req)
    if isinstance(bundle, dict):
        bundle = AnalyzeExecutionResponse.model_validate(bundle)

    openai_secret_path = str(request.openai_secret_path).strip() if request.openai_secret_path else None
    gcp_auth_credential = str(request.gcp_auth_credential).strip() if request.gcp_auth_credential else None

    event_rows, event_log_rows, metric_rows = await _load_db_rows_for_ai(
        execution_id=execution_id_int,
        include_event_rows=request.include_event_rows,
        event_rows_limit=safe_event_rows_limit,
        include_event_log_rows=request.include_event_log_rows,
        event_log_rows_limit=safe_event_log_rows_limit,
    )

    playbook_version = None
    if isinstance(bundle.playbook, dict):
        playbook_version = bundle.playbook.get("version")
    dry_run_commands, test_commands = _default_validation_commands(bundle.path, playbook_version)

    ai_payload: dict[str, Any] = {
        "target_execution_id": str(execution_id),
        "target_playbook_path": bundle.path,
        "target_playbook_status": bundle.status,
        "analysis_bundle": _json_ready(bundle.model_dump()),
        "event_rows": event_rows if request.include_event_rows else [],
        "event_log_rows": event_log_rows if request.include_event_log_rows else [],
        "metric_rows": metric_rows,
        "cloud_context": _json_ready(bundle.cloud),
        "ai_prompt": bundle.ai_prompt,
        "model": request.model,
        "include_patch_diff": request.include_patch_diff,
        "auto_fix_mode": auto_fix_mode,
        "approval_required": request.approval_required,
        "approved": request.approved,
        "default_dry_run_commands": dry_run_commands,
        "default_test_commands": test_commands,
    }
    if gcp_auth_credential:
        ai_payload["gcp_auth"] = gcp_auth_credential
    if openai_secret_path:
        ai_payload["openai_secret_path"] = openai_secret_path

    try:
        from noetl.server.api.core import ExecuteRequest as ExecuteRequest
        from noetl.server.api.core import execute as execute_playbook
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Execute endpoint is unavailable: {exc}") from exc

    try:
        ai_exec = await execute_playbook(
            ExecuteRequest(
                path=request.analysis_playbook_path,
                payload=ai_payload,
            )
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"AI analysis playbook not found: {request.analysis_playbook_path}. "
                    "Register tests/fixtures/playbooks/ops/execution_ai_analyze/execution_ai_analyze.yaml first."
                ),
            ) from exc
        raise

    ai_execution_id = int(ai_exec.execution_id)
    terminal_row, timed_out = await _wait_for_terminal_event(
        execution_id=ai_execution_id,
        timeout_seconds=request.timeout_seconds,
        poll_interval_ms=request.poll_interval_ms,
    )

    ai_report, ai_raw_output, ai_execution_status = await _load_ai_execution_output(ai_execution_id)
    if timed_out:
        ai_execution_status = "TIMEOUT"

    if not ai_report:
        ai_report = {
            "executive_summary": "AI report payload was not found in analyzer execution output.",
            "primary_bottlenecks": [],
            "failure_risk_analysis": [],
            "recommended_dsl_runtime_changes": [],
            "validation_plan": [],
            "proposed_patch_diff": "",
        }

    ai_report.setdefault("dry_run_commands", dry_run_commands)
    ai_report.setdefault("test_commands", test_commands)
    ai_report.setdefault("auto_fix_mode", auto_fix_mode)
    ai_report.setdefault("approval_required", request.approval_required)
    ai_report.setdefault("approved", request.approved)
    ai_report.setdefault(
        "apply_allowed",
        auto_fix_mode != "apply" or not request.approval_required or request.approved,
    )
    ai_report.setdefault("dry_run_recommended", True)

    if not request.include_patch_diff:
        ai_report["proposed_patch_diff"] = ""

    if terminal_row:
        ai_raw_output.setdefault("terminal_event", terminal_row)

    return AnalyzeExecutionWithAIResponse(
        execution_id=str(execution_id),
        path=bundle.path,
        status=bundle.status,
        generated_at=datetime.now(timezone.utc),
        bundle=bundle,
        ai_playbook_path=request.analysis_playbook_path,
        ai_execution_id=str(ai_execution_id),
        ai_execution_status=ai_execution_status,
        ai_report=_json_ready(ai_report),
        ai_raw_output=_json_ready(ai_raw_output),
        approval_required=request.approval_required,
        approved=request.approved,
        auto_fix_mode=auto_fix_mode,
        dry_run_recommended=True,
    )


@router.post("/executions/cleanup", response_model=CleanupStuckExecutionsResponse)
async def cleanup_stuck_executions(request: CleanupStuckExecutionsRequest = Body(...)):
    """
    Clean up stuck executions that have no terminal event.
    
    Marks executions as CANCELLED if they:
    - Have a 'playbook.initialized' event
    - Are older than specified minutes (default: 5)
    - Have no terminal event (playbook/workflow completed|failed, execution.cancelled)
    
    This is useful for cleaning up executions interrupted by server restarts.
    """
    logger.info(
        f"Cleanup stuck executions request: older_than_minutes={request.older_than_minutes}, "
        f"dry_run={request.dry_run}"
    )
    
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            # Find stuck executions
            await cursor.execute("""
                SELECT DISTINCT 
                    e1.execution_id,
                    e1.catalog_id
                FROM event e1
                WHERE e1.event_type = 'playbook.initialized'
                  AND e1.created_at < NOW() - INTERVAL '%s minutes'
                  AND NOT EXISTS (
                    SELECT 1 FROM event e2 
                    WHERE e2.execution_id = e1.execution_id 
                      AND e2.event_type IN (
                          'playbook.completed',
                          'workflow.completed',
                          'playbook.failed',
                          'workflow.failed',
                          'execution.cancelled'
                      )
                  )
                ORDER BY e1.execution_id
            """, (request.older_than_minutes,))
            
            stuck_executions = await cursor.fetchall()
            execution_ids = [str(ex['execution_id']) for ex in stuck_executions]
            
            if request.dry_run:
                logger.info(f"[DRY RUN] Would cancel {len(execution_ids)} stuck executions")
                return CleanupStuckExecutionsResponse(
                    cancelled_count=len(execution_ids),
                    execution_ids=execution_ids,
                    message=f"[DRY RUN] Would cancel {len(execution_ids)} stuck executions older than {request.older_than_minutes} minutes"
                )
            
            if not stuck_executions:
                return CleanupStuckExecutionsResponse(
                    cancelled_count=0,
                    execution_ids=[],
                    message=f"No stuck executions found older than {request.older_than_minutes} minutes"
                )
            
            # Insert cancellation events
            for execution in stuck_executions:
                execution_id = execution['execution_id']
                catalog_id = execution['catalog_id']
                
                # Get next event_id for this execution
                await cursor.execute("""
                    SELECT COALESCE(MAX(event_id), 0) + 1 as next_event_id
                    FROM event
                    WHERE execution_id = %s
                """, (execution_id,))
                
                result = await cursor.fetchone()
                next_event_id = result['next_event_id']
                
                # Insert cancellation event
                await cursor.execute("""
                    INSERT INTO event (
                        execution_id, catalog_id, event_id, event_type, status, context, created_at
                    ) VALUES (
                        %s, %s, %s, 'execution.cancelled', 'CANCELLED', %s, NOW()
                    )
                """, (
                    execution_id,
                    catalog_id,
                    next_event_id,
                    Json({
                        "reason": f"Cleaned up stuck execution (older than {request.older_than_minutes} minutes)",
                        "auto_cancelled": True,
                        "cleanup_api": True
                    })
                ))
            
            await conn.commit()
            
            logger.info(f"Cancelled {len(execution_ids)} stuck executions")
            
            return CleanupStuckExecutionsResponse(
                cancelled_count=len(execution_ids),
                execution_ids=execution_ids,
                message=f"Successfully cancelled {len(execution_ids)} stuck executions older than {request.older_than_minutes} minutes"
            )
