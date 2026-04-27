"""Model Context Protocol tool executor for NoETL workers."""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

import httpx
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def _read_float_env(name: str, default: float, min_value: float = 0.1) -> float:
    raw = os.getenv(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        return default
    return max(min_value, parsed)


def _resolve_timeout_seconds(timeout_value: Any) -> float:
    default_timeout = _read_float_env("NOETL_MCP_REQUEST_TIMEOUT_SECONDS", 60.0)
    command_timeout_budget = _read_float_env("NOETL_WORKER_COMMAND_TIMEOUT_SECONDS", 180.0, min_value=1.0)
    max_timeout = max(1.0, command_timeout_budget)

    if timeout_value is None or (isinstance(timeout_value, str) and not timeout_value.strip()):
        return min(default_timeout, max_timeout)

    try:
        parsed = float(timeout_value)
    except (TypeError, ValueError):
        return min(default_timeout, max_timeout)
    if not math.isfinite(parsed):
        return min(default_timeout, max_timeout)

    return min(max(0.1, parsed), max_timeout)


def _trim_slash(value: str) -> str:
    return str(value or "").rstrip("/")


def _parse_mcp_envelope(raw: Any, context: str) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError(f"Invalid MCP response for {context}: {type(raw).__name__}")

    data_lines = [
        line.replace("data:", "", 1).strip()
        for line in raw.splitlines()
        if line.startswith("data:")
    ]
    payload = "\n".join(data_lines) if data_lines else raw
    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        preview = " ".join(payload.split())[:360]
        raise ValueError(f"Invalid MCP response for {context}: {preview}") from exc


def _extract_text(result: Dict[str, Any]) -> str:
    content = result.get("content")
    if isinstance(content, list):
        parts = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and item.get("type") == "text" and item.get("text") is not None
        ]
        if parts:
            return "\n".join(parts)
    return json.dumps(result, default=str, separators=(",", ":"))


def _server_env_name(server: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in server.upper())
    return f"NOETL_MCP_{safe}_URL"


def _resolve_endpoint(config: Dict[str, Any], context: Dict[str, Any]) -> str:
    endpoint = (
        config.get("endpoint")
        or config.get("url")
        or config.get("server_url")
        or config.get("base_url")
    )
    server = str(config.get("server") or config.get("name") or "kubernetes")
    if not endpoint:
        mcp_servers = context.get("mcp_servers")
        if isinstance(mcp_servers, dict):
            server_config = mcp_servers.get(server)
            if isinstance(server_config, dict):
                endpoint = server_config.get("endpoint") or server_config.get("url")
            elif isinstance(server_config, str):
                endpoint = server_config
    if not endpoint:
        endpoint = os.getenv(_server_env_name(server)) or os.getenv("NOETL_MCP_URL")
    if not endpoint:
        raise ValueError(f"mcp endpoint is required for server '{server}'")
    return _trim_slash(str(endpoint))


def _resolve_health_endpoint(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    path = parts.path.rstrip("/")
    if path in {"/mcp", "/sse", "/message"}:
        path = "/healthz"
    else:
        path = f"{path}/healthz" if path else "/healthz"
    return urlunsplit((parts.scheme, parts.netloc, path, "", ""))


async def _post_jsonrpc(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: Dict[str, Any],
    *,
    session_id: Optional[str] = None,
) -> tuple[Dict[str, Any], httpx.Headers]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id

    response = await client.post(endpoint, json=payload, headers=headers)
    response.raise_for_status()
    envelope = _parse_mcp_envelope(response.text, str(payload.get("method") or "request"))
    if envelope.get("error"):
        error = envelope["error"]
        if isinstance(error, dict):
            raise RuntimeError(error.get("message") or json.dumps(error, default=str))
        raise RuntimeError(str(error))
    return envelope, response.headers


async def execute_mcp_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
) -> Dict[str, Any]:
    """Execute a JSON-RPC request against an MCP server.

    Supported actions:
    - `health`: GET `<endpoint>/healthz`
    - `tools/list`: initialize, then list tools
    - `tools/call`: initialize, then call one tool with `arguments`
    """
    server = "kubernetes"
    endpoint: Optional[str] = None
    method = "tools/call"
    params: Dict[str, Any] = {}

    try:
        rendered = render_template(jinja_env, dict(task_config or {}), context or {})
        rendered_input = render_template(jinja_env, dict(task_with or {}), context or {})
        config = {**rendered, **rendered_input}

        server = str(config.get("server") or "kubernetes")
        endpoint = _resolve_endpoint(config, context or {})
        method = str(config.get("method") or config.get("action") or "tools/call")
        timeout = _resolve_timeout_seconds(config.get("timeout_seconds"))
        request_id = int(config.get("request_id") or 1)

        async with httpx.AsyncClient(timeout=timeout) as client:
            if method == "health":
                response = await client.get(_resolve_health_endpoint(endpoint))
                response.raise_for_status()
                return {
                    "status": "ok",
                    "server": server,
                    "endpoint": endpoint,
                    "method": method,
                    "healthy": True,
                    "text": response.text,
                }

            init_envelope, init_headers = await _post_jsonrpc(
                client,
                endpoint,
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": str(config.get("protocol_version") or "2025-03-26"),
                        "capabilities": config.get("capabilities") or {},
                        "clientInfo": {
                            "name": str(config.get("client_name") or "noetl-worker"),
                            "version": str(config.get("client_version") or "0"),
                        },
                    },
                },
            )
            session_id = init_headers.get("mcp-session-id") or init_headers.get("Mcp-Session-Id")
            if not session_id:
                raise RuntimeError("MCP server did not return a session id")

            if method == "tools/call":
                tool_name = config.get("tool") or config.get("tool_name")
                if not tool_name:
                    raise ValueError("mcp tool name is required for tools/call")
                arguments = config.get("arguments")
                if arguments is None:
                    arguments = config.get("args")
                if arguments is None:
                    arguments = {}
                if isinstance(arguments, str):
                    arguments = json.loads(arguments)
                if not isinstance(arguments, dict):
                    raise ValueError("mcp arguments must be an object")
                params = {"name": str(tool_name), "arguments": arguments}
            elif method == "tools/list":
                params = {}
            else:
                params = config.get("params") or {}
                if isinstance(params, str):
                    params = json.loads(params)
                if not isinstance(params, dict):
                    raise ValueError("mcp params must be an object")

            envelope, _headers = await _post_jsonrpc(
                client,
                endpoint,
                {
                    "jsonrpc": "2.0",
                    "id": request_id + 1,
                    "method": method,
                    "params": params,
                },
                session_id=session_id,
            )

        result = envelope.get("result") or {}
        if not isinstance(result, dict):
            result = {"value": result}
        text = _extract_text(result)
        logger.debug("MCP request completed: server=%s method=%s endpoint=%s", server, method, endpoint)
        return {
            "status": "ok",
            "server": server,
            "endpoint": endpoint,
            "method": method,
            "tool": params.get("name") if isinstance(params, dict) else None,
            "arguments": params.get("arguments") if isinstance(params, dict) else None,
            "text": text,
            "result": result,
            "initialize": init_envelope.get("result"),
        }
    except (ValueError, RuntimeError, json.JSONDecodeError, httpx.HTTPError) as exc:
        logger.warning(
            "MCP request failed: server=%s method=%s endpoint=%s error=%s",
            server,
            method,
            endpoint,
            exc,
        )
        return {
            "status": "error",
            "server": server,
            "endpoint": endpoint,
            "method": method,
            "tool": params.get("name") if isinstance(params, dict) else None,
            "arguments": params.get("arguments") if isinstance(params, dict) else None,
            "error": str(exc),
            "text": str(exc),
        }
