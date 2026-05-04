"""Expose a registered playbook as an MCP-protocol JSON-RPC server.

This is the server-side counterpart of the existing MCP *client* executor in
``noetl.tools.mcp``: rather than calling out to a foreign MCP server, this
module *implements* the MCP server protocol on top of an arbitrary catalog
playbook. External MCP clients (Cursor, Claude Desktop, IDE plugins, peer
NoETL deployments) point at::

    POST /api/mcp/playbook/{path:path}/jsonrpc

and use the standard MCP handshake — ``initialize`` → ``tools/list`` →
``tools/call`` — to discover and invoke the playbook as a tool.

Why this lives in ``server/api/mcp`` and not ``tools/mcp``:

* It is a *server* concern: it decides what tools to advertise based on
  catalog content, runs auth checks, dispatches the playbook through the
  existing ``/api/execute`` plumbing, and waits for the result. It needs
  the FastAPI request lifecycle and the catalog service.
* The existing ``noetl.tools.mcp`` module is a *client* — it talks
  HTTP/JSON-RPC to a remote MCP server. The two will never share types
  beyond the wire shape, which is small enough to inline.

Scope of the spike (Gap 2 in the NoETL-as-AI-OS architecture issue):

* Implements the three MCP protocol methods that matter for tool
  composition — ``initialize``, ``tools/list``, ``tools/call``.
* Advertises *one* tool per endpoint: the playbook itself. Tool name
  defaults to the playbook's ``metadata.name``, falling back to the path
  basename. ``inputSchema`` is derived from the existing
  ``infer_ui_schema`` helper so we don't redefine the workload contract.
* ``tools/call`` is *synchronous*: dispatches the playbook, polls the
  execution status until terminal (or until a ceiling timeout hits), and
  returns the result envelope as MCP content blocks. Async tool calls
  (with progress notifications) are out of scope here — they can land
  on top of this once the SSE plumbing for parent ↔ child execution
  events is wired in (tracked separately as Gap 2.1).
* Honours ``metadata.exposes_as_mcp: true`` when present (Gap 3 will add
  the Pydantic field; for the spike we read it directly from the parsed
  payload). When the field is absent we fall back to "any registered
  playbook" so existing fixtures can be exercised end-to-end before
  Gap 3 lands.
* Does NOT yet wire the sub-execution into the parent's child-execution
  graph beyond returning the ``execution_id`` in the response — the
  caller is on a peer MCP wire, not a parent NoETL execution. That graph
  link only matters when a peer playbook calls *us* via ``tool: agent
  framework=noetl`` (Gap 1) and is the correct place to attach it.

Tests live alongside the noetl tree at ``tests/unit/server/api/mcp`` and
in the ai-meta sandbox at ``scripts/playbook_as_mcp_smoke.py`` (the
hand-rolled stub harness we use when PyPI is blocked).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import HTTPException

from noetl.core.logger import setup_logger

from . import service as mcp_service
from .ui_schema import infer_ui_schema

logger = setup_logger(__name__, include_location=True)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# MCP protocol version we support. Bumped to match the version Cursor /
# Claude Desktop currently negotiate. Clients sending an older version
# string are answered with the same string they sent (per MCP protocol)
# so they don't reject the response.
_DEFAULT_PROTOCOL_VERSION = "2024-11-05"

# Server identity returned in the ``initialize`` response. ``version``
# is the playbook-mcp surface version, NOT the server's release tag —
# clients that key off this string for compatibility shims should see a
# stable identifier here regardless of which noetl image is running.
_SERVER_INFO = {"name": "noetl-playbook-mcp", "version": "1.0"}

# JSON-RPC 2.0 error codes we use. The reserved range -32700..-32600 is
# protocol-defined; -32000..-32099 is the "server error" range we may
# allocate freely. We pick stable values so clients can branch on them.
_JSONRPC_PARSE_ERROR = -32700
_JSONRPC_INVALID_REQUEST = -32600
_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_INVALID_PARAMS = -32602
_JSONRPC_INTERNAL_ERROR = -32603
_JSONRPC_PLAYBOOK_FAILED = -32010  # playbook ran to completion but reported error
_JSONRPC_PLAYBOOK_TIMEOUT = -32011  # poll loop hit ceiling without terminal status
_JSONRPC_AUTH_DENIED = -32020  # auth backend denied access (mirrors HTTP 403)

# Default poll ceiling for ``tools/call``. MCP clients on the other end
# of this wire have their own timeouts (Cursor: 120s; Claude Desktop:
# 60s last we measured), so anything beyond ~90s would just race a
# client-side cancel and burn worker capacity. Configurable via
# ``MCP_PLAYBOOK_CALL_TIMEOUT_SECONDS`` env if a deployment needs more.
_DEFAULT_CALL_TIMEOUT_SECONDS = 90.0
_DEFAULT_CALL_POLL_INTERVAL_SECONDS = 1.5


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def dispatch_jsonrpc(
    *,
    catalog_service,
    execute_callable: Callable[..., Awaitable[str]],
    status_callable: Callable[[str], Awaitable[dict[str, Any]]],
    path: str,
    body: Any,
    auth_check_callable: Optional[Callable[..., Awaitable[None]]] = None,
    call_timeout_seconds: float = _DEFAULT_CALL_TIMEOUT_SECONDS,
    poll_interval_seconds: float = _DEFAULT_CALL_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """Dispatch a single JSON-RPC request against the playbook at ``path``.

    All collaborators are injected so the unit tests can swap fakes in
    without standing up the catalog / execute / status machinery:

    * ``catalog_service`` — the CatalogService class (or a stand-in
      that exposes ``fetch_entry``)
    * ``execute_callable(path, workload) -> execution_id`` — dispatches
      the playbook, returns the started execution id (matches the
      lifecycle endpoint's contract)
    * ``status_callable(execution_id) -> status_dict`` — returns the
      most recent status snapshot. Must include at least
      ``{"completed": bool, "failed": bool, "result": Any}``. The
      production wiring delegates to ``GET /executions/{id}/status``.
    * ``auth_check_callable(playbook_path, action)`` — optional
      enforce-mode auth hook. Mirrors the lifecycle dispatcher.

    Returns the JSON-RPC 2.0 *response* envelope. Errors are returned
    as ``{"jsonrpc": "2.0", "id": ..., "error": {"code", "message",
    "data"?}}`` rather than HTTP errors so the client sees them as
    protocol-level failures (which is what MCP spec mandates) rather
    than transport-level ones.
    """
    rpc_id, method, params = _parse_envelope(body)

    try:
        if method == "initialize":
            return _ok(rpc_id, _initialize_result(params))
        if method == "tools/list":
            tool = await _build_tool_spec(catalog_service, path)
            return _ok(rpc_id, {"tools": [tool]})
        if method == "tools/call":
            return await _handle_tools_call(
                catalog_service=catalog_service,
                execute_callable=execute_callable,
                status_callable=status_callable,
                auth_check_callable=auth_check_callable,
                path=path,
                rpc_id=rpc_id,
                params=params,
                call_timeout_seconds=call_timeout_seconds,
                poll_interval_seconds=poll_interval_seconds,
            )
        if method == "ping":
            # Optional but cheap; lets clients keep the connection warm
            # and verify the server is alive without committing to a tool
            # call.
            return _ok(rpc_id, {})

        return _err(
            rpc_id,
            _JSONRPC_METHOD_NOT_FOUND,
            f"method '{method}' is not implemented; supported: "
            "initialize, tools/list, tools/call, ping",
        )
    except HTTPException as exc:
        # Auth denials and catalog-not-found surface as HTTPException
        # from the service layer. Map to JSON-RPC errors so the MCP
        # client sees them in-band; status_code is preserved in
        # error.data.http_status for clients that want it.
        code = (
            _JSONRPC_AUTH_DENIED
            if exc.status_code in (401, 403)
            else _JSONRPC_INVALID_REQUEST
            if exc.status_code in (400, 404, 422)
            else _JSONRPC_INTERNAL_ERROR
        )
        return _err(
            rpc_id,
            code,
            str(exc.detail or exc),
            data={"http_status": exc.status_code},
        )
    except Exception as exc:  # pragma: no cover -- unexpected bugs
        logger.exception("playbook_mcp.dispatch_jsonrpc failed")
        return _err(
            rpc_id,
            _JSONRPC_INTERNAL_ERROR,
            f"internal error: {exc}",
        )


# ---------------------------------------------------------------------------
# Method handlers
# ---------------------------------------------------------------------------


def _initialize_result(params: dict[str, Any]) -> dict[str, Any]:
    """Build the ``initialize`` response.

    Echoes the client's ``protocolVersion`` if it sent one, falling back
    to our default. MCP's negotiation rule is that the server may pick
    a version <= the client's; echoing keeps the simple case simple and
    avoids spurious downgrade warnings.
    """
    requested = params.get("protocolVersion") if isinstance(params, dict) else None
    return {
        "protocolVersion": str(requested or _DEFAULT_PROTOCOL_VERSION),
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": dict(_SERVER_INFO),
    }


async def _build_tool_spec(catalog_service, path: str) -> dict[str, Any]:
    """Materialize the MCP tool descriptor for the playbook at ``path``.

    Reuses ``infer_ui_schema`` so the inputSchema mirrors the workload
    form the GUI renders for the same playbook. This means a tool the
    user runs from the GUI and a tool an MCP client calls take the
    *same* arguments — no schema drift.
    """
    entry = await mcp_service.fetch_any_resource(catalog_service, path, "latest")
    kind = (entry.get("kind") or "").lower()
    if kind not in ("playbook", "agent"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"resource '{path}' is kind='{kind}'; "
                "playbook-as-MCP requires kind 'playbook' or 'agent'"
            ),
        )

    payload = entry.get("payload") or _safe_yaml_load(entry.get("content")) or {}
    metadata = payload.get("metadata") if isinstance(payload, dict) else {}
    metadata = metadata if isinstance(metadata, dict) else {}

    # Soft Gap 3 enforcement: when the playbook explicitly opts out
    # (exposes_as_mcp=false) we 403; when absent or true, allow.
    exposes_flag = metadata.get("exposes_as_mcp")
    if exposes_flag is False:
        raise HTTPException(
            status_code=403,
            detail=(
                f"playbook '{path}' has metadata.exposes_as_mcp=false; "
                "set it to true (or omit) to expose via MCP"
            ),
        )

    tool_name = _coerce_tool_name(metadata.get("name") or path)
    description = metadata.get("description") or _default_description(path, kind)
    input_schema = _input_schema_from_ui_schema(entry.get("content") or "")

    return {
        "name": tool_name,
        "description": description,
        "inputSchema": input_schema,
    }


async def _handle_tools_call(
    *,
    catalog_service,
    execute_callable: Callable[..., Awaitable[str]],
    status_callable: Callable[[str], Awaitable[dict[str, Any]]],
    auth_check_callable: Optional[Callable[..., Awaitable[None]]],
    path: str,
    rpc_id: Any,
    params: dict[str, Any],
    call_timeout_seconds: float,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    """Dispatch the playbook + poll until terminal + return MCP content.

    Validates that the requested tool name matches the one we advertised
    in ``tools/list``. This keeps clients honest — if they asked for
    tool ``foo`` but our spec said ``bar``, that's almost certainly a
    catalog version drift on the client side and we want to fail loud.
    """
    if not isinstance(params, dict):
        return _err(rpc_id, _JSONRPC_INVALID_PARAMS, "params must be an object")

    requested_tool = str(params.get("name") or "")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}

    spec = await _build_tool_spec(catalog_service, path)
    if requested_tool and requested_tool != spec["name"]:
        return _err(
            rpc_id,
            _JSONRPC_INVALID_PARAMS,
            f"tool '{requested_tool}' is not exposed by this endpoint; "
            f"expected '{spec['name']}'",
        )

    if auth_check_callable is not None:
        await auth_check_callable(playbook_path=path, action="execute")

    try:
        execution_id = await execute_callable(path=path, workload=arguments)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("playbook_mcp execute dispatch failed")
        return _err(
            rpc_id,
            _JSONRPC_INTERNAL_ERROR,
            f"failed to dispatch playbook: {exc}",
        )

    deadline = time.monotonic() + max(1.0, float(call_timeout_seconds))
    last_status: dict[str, Any] = {}
    while True:
        last_status = await status_callable(execution_id) or {}
        if last_status.get("completed") or last_status.get("failed"):
            break
        if time.monotonic() >= deadline:
            return _err(
                rpc_id,
                _JSONRPC_PLAYBOOK_TIMEOUT,
                f"playbook '{path}' did not reach terminal status within "
                f"{call_timeout_seconds:.0f}s; check execution {execution_id}",
                data={"execution_id": execution_id, "status": last_status},
            )
        await asyncio.sleep(max(0.1, float(poll_interval_seconds)))

    is_error = bool(last_status.get("failed"))
    text_payload = _extract_text(last_status)

    return _ok(
        rpc_id,
        {
            "content": [{"type": "text", "text": text_payload}],
            "isError": is_error,
            # Non-standard fields (alongside content) carry NoETL identity
            # so callers can stitch the MCP call back into our event log.
            # MCP spec does NOT forbid extra fields in the result object.
            "_meta": {
                "noetl_execution_id": execution_id,
                "noetl_path": path,
            },
        },
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_envelope(body: Any) -> tuple[Any, str, dict[str, Any]]:
    """Decompose a JSON-RPC request into (id, method, params).

    Returns rpc_id=None when the envelope is missing it (notification
    request); the caller will produce a response with ``"id": null``.
    Raises HTTPException(400) only when the body is so malformed we
    can't even extract an id — e.g. a non-dict payload. Other shape
    issues are returned as JSON-RPC errors so the client gets the
    expected envelope.
    """
    if not isinstance(body, dict):
        raise HTTPException(
            status_code=400,
            detail="JSON-RPC request body must be a JSON object",
        )
    rpc_id = body.get("id")
    method = body.get("method")
    if not isinstance(method, str):
        return rpc_id, "", body.get("params") or {}
    params = body.get("params")
    return rpc_id, method, params if isinstance(params, dict) else {}


def _ok(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _err(
    rpc_id: Any,
    code: int,
    message: str,
    *,
    data: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": int(code), "message": str(message)}
    if data:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": error}


def _coerce_tool_name(raw: str) -> str:
    """MCP tool names should be filesystem-safe; map slashes / spaces.

    We keep the tool name human-readable rather than hashing — the
    common case (Cursor, Claude Desktop) shows the tool name verbatim
    in the UI and a hash would just look like garbage.
    """
    cleaned = (raw or "").strip().replace("/", ".").replace(" ", "_")
    return cleaned or "noetl_playbook"


def _default_description(path: str, kind: str) -> str:
    return (
        f"NoETL {kind} '{path}'. Invoking this tool dispatches the playbook "
        "with the supplied workload and waits for completion."
    )


def _input_schema_from_ui_schema(content: str) -> dict[str, Any]:
    """Translate the inferred UI fields into a JSON-schema for MCP.

    MCP's ``inputSchema`` is a JSON-schema-ish object; we produce
    ``{type: 'object', properties: {...}, additionalProperties: true}``
    so callers can pass extra workload keys our schema didn't predict.
    The kind→json-schema mapping follows the same conventions
    ``infer_ui_schema`` already uses.
    """
    fields = []
    if content:
        try:
            fields = list(infer_ui_schema(content) or [])
        except Exception:
            logger.warning("infer_ui_schema failed; emitting empty schema", exc_info=True)
            fields = []

    properties: dict[str, Any] = {}
    for f in fields:
        # ``f`` may be a Pydantic model or a dict depending on caller.
        # Normalise to dict view.
        if hasattr(f, "model_dump"):
            f = f.model_dump()
        if not isinstance(f, dict):
            continue
        name = f.get("name")
        if not name:
            continue
        prop: dict[str, Any] = {"type": _ui_kind_to_json_type(f.get("kind"))}
        if f.get("description"):
            prop["description"] = str(f["description"])
        if f.get("default") is not None:
            prop["default"] = f["default"]
        if f.get("options"):
            prop["enum"] = list(f["options"])
        properties[str(name)] = prop

    return {
        "type": "object",
        "properties": properties,
        "additionalProperties": True,
    }


def _ui_kind_to_json_type(kind: Any) -> str:
    mapping = {
        "string": "string",
        "integer": "integer",
        "number": "number",
        "boolean": "boolean",
        "object": "object",
        "array": "array",
        "null": "null",
        "enum": "string",
    }
    return mapping.get(str(kind or "").lower(), "string")


def _extract_text(status: dict[str, Any]) -> str:
    """Best-effort: pull a useful text payload out of an execution status.

    Mirrors the GUI's ``extractAgentText`` heuristic: prefer
    ``result.text``, then ``result.summary``, then ``result.message``,
    then a compact JSON dump. We accept ``status.result`` directly
    OR the ``status`` itself being result-shaped (the status_callable
    contract leaves room for both, since some callers fold them).
    """
    candidates = []
    result = status.get("result")
    if isinstance(result, dict):
        candidates.append(result)
    candidates.append(status)

    for c in candidates:
        if not isinstance(c, dict):
            continue
        for key in ("text", "summary", "message", "user_message", "output"):
            v = c.get(key)
            if isinstance(v, str) and v.strip():
                return v
            if isinstance(v, dict):
                # nested {text|summary|message|...}
                for inner in ("text", "summary", "message"):
                    iv = v.get(inner)
                    if isinstance(iv, str) and iv.strip():
                        return iv

    # Fall through: dump whatever we have so the client at least sees
    # the shape. Cap to keep the wire payload reasonable.
    try:
        rendered = json.dumps(result if isinstance(result, dict) else status, default=str, sort_keys=True)
    except (TypeError, ValueError):
        rendered = str(status)
    if len(rendered) > 8000:
        rendered = rendered[:8000] + "...[truncated]"
    return rendered


def _safe_yaml_load(content: Any) -> Optional[dict[str, Any]]:
    if not isinstance(content, str) or not content.strip():
        return None
    try:
        import yaml as _yaml

        parsed = _yaml.safe_load(content)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None
