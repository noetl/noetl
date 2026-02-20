from noetl.server.api.catalog.schema import (
    CatalogEntry,
    CatalogEntryRequest,
    CatalogEntriesRequest,
    CatalogEntries,
    CatalogRegisterRequest,
    CatalogRegisterResponse,
    ExplainPlaybookWithAIRequest,
    ExplainPlaybookWithAIResponse,
    GeneratePlaybookWithAIRequest,
    GeneratePlaybookWithAIResponse,
)
from .service import CatalogService, get_catalog_service
from fastapi import APIRouter, Depends, Request, HTTPException, Body
from fastapi.responses import JSONResponse
from noetl.core.logger import setup_logger
import base64
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Any, Optional

from psycopg.rows import dict_row

from noetl.core.db.pool import get_pool_connection

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
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
    current = _parse_json_text(value)
    for _ in range(6):
        if not isinstance(current, dict):
            return current
        if "ai_report" in current:
            return current
        if current.get("kind") in {"data", "ref", "refs"} and "data" in current:
            current = _parse_json_text(current.get("data"))
            continue
        if "result" in current:
            current = _parse_json_text(current.get("result"))
            continue
        if "data" in current:
            current = _parse_json_text(current.get("data"))
            continue
        return current
    return current


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
    return status or "UNKNOWN"


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


async def _load_ai_playbook_output(
    ai_execution_id: int,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """
                SELECT event_type, status, created_at
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
    fallback_payload: dict[str, Any] = {}

    for row in rows:
        payload = _unwrap_result_payload(row.get("result"))
        if isinstance(payload, dict):
            if not fallback_payload:
                fallback_payload = _json_ready(payload)

            has_report = isinstance(payload.get("ai_report"), dict)
            has_generated = bool(_extract_generated_playbook(payload))
            if has_report or has_generated:
                ai_raw_output = _json_ready(payload)
                if has_report:
                    ai_report = _json_ready(payload.get("ai_report"))
                break

    if not ai_raw_output and fallback_payload:
        ai_raw_output = fallback_payload

    if not ai_raw_output and rows:
        first_row = rows[0]
        ai_raw_output = {
            "node_name": first_row.get("node_name"),
            "event_type": first_row.get("event_type"),
            "status": first_row.get("status"),
            "error": first_row.get("error"),
            "result": _json_ready(_unwrap_result_payload(first_row.get("result"))),
        }

    status = _derive_execution_terminal_status(dict(latest_row) if latest_row else None)
    return ai_report, ai_raw_output, status


def _extract_generated_playbook(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("generated_playbook_yaml"),
        payload.get("generated_playbook"),
        payload.get("playbook_yaml"),
        payload.get("yaml"),
    ]
    nested = payload.get("draft")
    if isinstance(nested, dict):
        candidates.extend(
            [
                nested.get("generated_playbook_yaml"),
                nested.get("generated_playbook"),
                nested.get("playbook_yaml"),
                nested.get("yaml"),
            ]
        )
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


@router.post(
    "/catalog/register",
    response_model=CatalogRegisterResponse,
    tags=["Catalog"],
    summary="Register a new catalog resource",
    description="""
Register a new catalog resource (Playbook, Tool, Model, etc.) with version control.

**Request Body:**
- `content`: YAML content of the resource (accepts base64 encoded or plain text)
- `resource_type`: Type of resource to register (default: "Playbook")

**Behavior:**
- Automatically increments version if resource already exists at the same path
- Extracts metadata (name, path, kind) from YAML content
- Validates resource structure before registration

**Returns:**
- Registration confirmation with catalog_id, path, version, and kind

**Examples:**

Register a new Playbook:
```json
POST /catalog/register
{
  "content": "apiVersion: noetl.io/v1\\nkind: Playbook\\nmetadata:\\n  name: example\\n  path: tests/fixtures/playbooks/hello_world/hello_world\\n...",
  "resource_type": "Playbook"
}
```

Register with base64 encoded content:
```json
POST /catalog/register
{
  "content": "YXBpVmVyc2lvbjogbm9ldGwuaW8vdjEKa2luZDogUGxheWJvb2s=",
  "resource_type": "Playbook"
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Resource 'tests/fixtures/playbooks/hello_world/hello_world' version '1' registered.",
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": 1,
  "catalog_id": "478775660589088776",
  "kind": "Playbook"
}
```
    """
)
async def register_resource(
    request: CatalogRegisterRequest,
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    try:
        result = await catalog_service.register_resource(request.content, request.resource_type)
        return CatalogRegisterResponse(**result)
    except Exception as e:
        logger.exception(f"Error registering resource: {e}.")
        raise HTTPException(
            status_code=500,
            detail=f"Error registering resource: {e}."
        )


@router.post(
    "/catalog/list",
    response_model=CatalogEntries,
    tags=["Catalog"],
    summary="List all catalog resources",
    description="""
Retrieve a list of all catalog entries, optionally filtered by resource type.

**Request Body:**
- `resource_type` (optional): Filter by resource kind (e.g., "Playbook", "Tool", "Model")

**Returns:**
- List of catalog entries ordered by creation date (newest first)
- Each entry includes: path, kind, version, content, layout, payload, meta, created_at

**Examples:**

Get all resources:
```json
POST /catalog/list
{}
```

Get only Playbooks:
```json
POST /catalog/list
{
  "resource_type": "Playbook"
}
```

**Response:**
```json
{
  "entries": [
    {
      "path": "tests/fixtures/playbooks/hello_world/hello_world",
      "kind": "Playbook",
      "version": 2,
      "content": "apiVersion: noetl.io/v1...",
      "payload": {...},
      "meta": {...},
      "created_at": "2025-10-24T12:00:00Z"
    }
  ]
}
```
    """
)
async def list_resources(
    request: Request,
    payload: CatalogEntriesRequest,
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    try:
        return await catalog_service.fetch_entries(payload.resource_type)
    except Exception as e:
        logger.exception(f"Error listing resources: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error listing resources: {e}"
        )


@router.post(
    "/catalog/resource",
    response_model=CatalogEntry,
    tags=["Catalog"],
    summary="Get catalog resource versions",
    description="""
Retrieve catalog resource(s) using unified lookup strategies.

**Supported Lookup Strategies** (priority order):
1. `catalog_id`: Direct catalog entry lookup (highest priority)
2. `path` + `version`: Version-controlled path-based lookup

**Request Body:**
- **Identifiers** (at least one required):
  - `catalog_id`: Direct catalog entry ID
  - `path`: Catalog path for resource
  - `version`: Version identifier (default: "latest")

**Returns:**
- Single resource if `catalog_id` or `path`+`version` specified
- Latest version if only `path` specified
- Each entry includes: path, kind, version, content, layout, payload, meta, created_at

**Examples:**

Get specific version by catalog_id:
```json
POST /catalog/resource
{
  "catalog_id": "123456789"
}
```

Get specific version by path and version:
```json
POST /catalog/resource
{
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": 2
}
```

Get latest version:
```json
POST /catalog/resource
{
  "path": "tests/fixtures/playbooks/hello_world/hello_world",
  "version": "latest"
}
```

Get all versions of a resource:
```json
POST /catalog/resource
{
  "path": "tests/fixtures/playbooks/hello_world/hello_world"
}
```

**Response:**
```json
[
  {
    "path": "tests/fixtures/playbooks/hello_world/hello_world",
    "kind": "Playbook",
    "version": 2,
    "content": "apiVersion: noetl.io/v1...",
    "payload": {...},
    "meta": {...},
    "created_at": "2025-10-24T12:00:00Z"
  }
]
```
    """
)
async def get_catalog_entry(
    payload: CatalogEntryRequest,
    catalog_service: CatalogService = Depends(get_catalog_service)
):
    """Get catalog resource(s) using unified lookup strategies"""
    result = await catalog_service.get(
        path=payload.path, 
        version=payload.version, 
        catalog_id=payload.catalog_id
    )
    # Return single entry or raise 404
    if not result:
        raise HTTPException(status_code=404, detail="Catalog entry not found")
    return result


@router.post(
    "/catalog/playbooks/explain/ai",
    response_model=ExplainPlaybookWithAIResponse,
    tags=["Catalog"],
    summary="Explain a playbook with AI",
)
async def explain_playbook_with_ai(
    request: ExplainPlaybookWithAIRequest = Body(...),
    catalog_service: CatalogService = Depends(get_catalog_service),
):
    try:
        target = await catalog_service.get(
            catalog_id=request.catalog_id,
            path=request.path,
            version=request.version,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not target:
        raise HTTPException(status_code=404, detail="Target playbook not found in catalog")
    if target.kind != "Playbook":
        raise HTTPException(status_code=400, detail=f"Catalog entry kind must be Playbook, got {target.kind}")

    payload: dict[str, Any] = {
        "target_playbook_catalog_id": str(target.catalog_id),
        "target_playbook_path": target.path,
        "target_playbook_version": int(target.version),
        "target_playbook_kind": target.kind,
        "target_playbook_content": target.content or "",
        "target_playbook_payload": target.payload or {},
        "model": request.model,
    }
    if request.gcp_auth_credential:
        payload["gcp_auth"] = request.gcp_auth_credential
    if request.openai_secret_path:
        payload["openai_secret_path"] = request.openai_secret_path

    try:
        from noetl.server.api.v2 import ExecuteRequest as V2ExecuteRequest
        from noetl.server.api.v2 import execute as execute_v2
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"V2 execute endpoint is unavailable: {exc}") from exc

    try:
        ai_exec = await execute_v2(
            V2ExecuteRequest(
                path=request.explanation_playbook_path,
                payload=payload,
            )
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"AI explain playbook not found: {request.explanation_playbook_path}. "
                    "Register tests/fixtures/playbooks/ops/playbook_ai_explain/playbook_ai_explain.yaml first."
                ),
            ) from exc
        raise

    ai_execution_id = int(ai_exec.execution_id)
    terminal_row, timed_out = await _wait_for_terminal_event(
        execution_id=ai_execution_id,
        timeout_seconds=request.timeout_seconds,
        poll_interval_ms=request.poll_interval_ms,
    )

    ai_report, ai_raw_output, ai_execution_status = await _load_ai_playbook_output(ai_execution_id)
    if timed_out:
        ai_execution_status = "TIMEOUT"
    if terminal_row:
        ai_raw_output.setdefault("terminal_event", terminal_row)
        ai_execution_status = _derive_execution_terminal_status(terminal_row)

    if not ai_report:
        ai_report = {
            "executive_summary": "No structured explanation returned by AI playbook.",
            "architecture_overview": "",
            "step_by_step": [],
            "risks": [],
            "improvement_opportunities": [],
            "test_recommendations": [],
        }

    return ExplainPlaybookWithAIResponse(
        target_path=target.path,
        target_version=target.version,
        generated_at=datetime.now(timezone.utc),
        ai_playbook_path=request.explanation_playbook_path,
        ai_execution_id=str(ai_execution_id),
        ai_execution_status=ai_execution_status,
        ai_report=_json_ready(ai_report),
        ai_raw_output=_json_ready(ai_raw_output),
    )


@router.post(
    "/catalog/playbooks/generate/ai",
    response_model=GeneratePlaybookWithAIResponse,
    tags=["Catalog"],
    summary="Generate a playbook draft with AI",
)
async def generate_playbook_with_ai(
    request: GeneratePlaybookWithAIRequest = Body(...),
):
    payload: dict[str, Any] = {
        "prompt": request.prompt,
        "model": request.model,
    }
    if request.gcp_auth_credential:
        payload["gcp_auth"] = request.gcp_auth_credential
    if request.openai_secret_path:
        payload["openai_secret_path"] = request.openai_secret_path

    try:
        from noetl.server.api.v2 import ExecuteRequest as V2ExecuteRequest
        from noetl.server.api.v2 import execute as execute_v2
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"V2 execute endpoint is unavailable: {exc}") from exc

    try:
        ai_exec = await execute_v2(
            V2ExecuteRequest(
                path=request.generator_playbook_path,
                payload=payload,
            )
        )
    except HTTPException as exc:
        if exc.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"AI generator playbook not found: {request.generator_playbook_path}. "
                    "Register tests/fixtures/playbooks/ops/playbook_ai_generate/playbook_ai_generate.yaml first."
                ),
            ) from exc
        raise

    ai_execution_id = int(ai_exec.execution_id)
    terminal_row, timed_out = await _wait_for_terminal_event(
        execution_id=ai_execution_id,
        timeout_seconds=request.timeout_seconds,
        poll_interval_ms=request.poll_interval_ms,
    )

    ai_report, ai_raw_output, ai_execution_status = await _load_ai_playbook_output(ai_execution_id)
    if timed_out:
        ai_execution_status = "TIMEOUT"
    if terminal_row:
        ai_raw_output.setdefault("terminal_event", terminal_row)
        ai_execution_status = _derive_execution_terminal_status(terminal_row)

    generated_playbook = _extract_generated_playbook(ai_raw_output)
    if not generated_playbook and isinstance(ai_report, dict):
        generated_playbook = _extract_generated_playbook(ai_report)
    if not generated_playbook:
        raise HTTPException(
            status_code=500,
            detail=(
                "AI generator playbook completed but no generated playbook text was returned. "
                f"AI execution status: {ai_execution_status}"
            ),
        )

    return GeneratePlaybookWithAIResponse(
        generated_at=datetime.now(timezone.utc),
        ai_playbook_path=request.generator_playbook_path,
        ai_execution_id=str(ai_execution_id),
        ai_execution_status=ai_execution_status,
        generated_playbook=generated_playbook,
        ai_report=_json_ready(ai_report),
        ai_raw_output=_json_ready(ai_raw_output),
    )
