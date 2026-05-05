"""MCP-protocol JSON-RPC server that fronts a local Ollama instance.

Wire shape: standard MCP — ``initialize`` / ``tools/list`` / ``tools/call``
over POST JSON. Tools exposed:

    chat           — chat completion against an Ollama model
    generate       — single-prompt completion (the simpler /api/generate)
    list_models    — return the local model registry

The bridge stays deliberately thin. It does NOT:

* Cache responses (Ollama is fast enough locally; playbooks have their
  own retry/cache layers).
* Stream responses back over the JSON-RPC wire (we wait for full
  completion and return the assembled text). Streaming would require
  a different transport — Server-Sent Events or a websocket — and the
  MCP spec for streaming is still in flux.
* Auth-gate calls. The bridge is meant to run on the cluster's private
  network; expose it with a NetworkPolicy, not auth tokens. Adding
  per-call auth would make this much heavier than it needs to be for
  a spike.

Design notes:

* We use ``aiohttp`` for the upstream Ollama call because that's what
  noetl's existing http tool ships with — adding a new HTTP client
  dependency for a sidecar would be silly. If aiohttp isn't installed
  we fall back to the stdlib ``urllib`` in a thread executor (slower
  but functional). Tests verify both paths.
* The HTTP framework on the inbound side is FastAPI — same as the
  rest of the server. The bridge can run standalone via uvicorn or
  embedded in a host process via ``build_app()``.
* Errors from Ollama (model not found, server crashed, etc.) surface
  as JSON-RPC application-level errors with code -32030, not as HTTP
  5xx, so MCP clients see them as "the tool returned an error" rather
  than transport failures.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


_DEFAULT_OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
_DEFAULT_TIMEOUT_SECONDS = float(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "120"))
_DEFAULT_PROTOCOL_VERSION = "2024-11-05"
_SERVER_INFO = {"name": "noetl-ollama-bridge", "version": "1.0"}

_JSONRPC_METHOD_NOT_FOUND = -32601
_JSONRPC_INVALID_PARAMS = -32602
_JSONRPC_INTERNAL_ERROR = -32603
_JSONRPC_OLLAMA_FAILED = -32030  # upstream Ollama returned non-2xx or malformed body


# ---------------------------------------------------------------------------
# MCP tool descriptors
# ---------------------------------------------------------------------------


_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "chat",
        "description": (
            "Chat completion against a local Ollama model. Pass `messages` "
            "as an array of {role, content} entries (OpenAI-compatible "
            "shape). `model` is required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Ollama model tag, e.g. 'gemma2:9b'"},
                "messages": {
                    "type": "array",
                    "description": "OpenAI-style messages: [{role: 'user'|'system'|'assistant', content: ...}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["role", "content"],
                    },
                },
                "temperature": {"type": "number", "default": 0.2},
                "system": {
                    "type": "string",
                    "description": "Optional system prompt; merged into messages if provided",
                },
            },
            "required": ["model", "messages"],
        },
    },
    {
        "name": "generate",
        "description": "Single-prompt completion (simpler than chat — no message history).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string"},
                "prompt": {"type": "string"},
                "temperature": {"type": "number", "default": 0.2},
                "system": {"type": "string"},
            },
            "required": ["model", "prompt"],
        },
    },
    {
        "name": "list_models",
        "description": "Return the list of locally pulled Ollama models.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def dispatch_jsonrpc(
    body: Any,
    *,
    ollama_url: str = _DEFAULT_OLLAMA_URL,
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    http_post: Optional[Any] = None,
    http_get: Optional[Any] = None,
) -> dict[str, Any]:
    """Dispatch a single MCP JSON-RPC request against the bridge.

    ``http_post`` / ``http_get`` are injectable so the unit tests can
    stub the upstream Ollama calls without standing up a real server.
    Each takes ``(url, payload?) -> dict`` and returns the parsed JSON
    response body. When omitted, we use the default in-process clients.
    """
    if not isinstance(body, dict):
        return _err(None, _JSONRPC_INVALID_PARAMS, "JSON-RPC body must be a JSON object")

    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") if isinstance(body.get("params"), dict) else {}

    try:
        if method == "initialize":
            return _ok(rpc_id, {
                "protocolVersion": str(params.get("protocolVersion") or _DEFAULT_PROTOCOL_VERSION),
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": dict(_SERVER_INFO),
            })

        if method == "tools/list":
            return _ok(rpc_id, {"tools": list(_TOOL_SPECS)})

        if method == "tools/call":
            tool_name = str(params.get("name") or "")
            arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
            return await _handle_tools_call(
                rpc_id=rpc_id,
                tool_name=tool_name,
                arguments=arguments,
                ollama_url=ollama_url,
                timeout_seconds=timeout_seconds,
                http_post=http_post,
                http_get=http_get,
            )

        if method == "ping":
            return _ok(rpc_id, {})

        return _err(
            rpc_id,
            _JSONRPC_METHOD_NOT_FOUND,
            f"method '{method}' not implemented",
        )
    except Exception as exc:  # pragma: no cover -- unexpected bug
        logger.exception("ollama_bridge.dispatch_jsonrpc failed")
        return _err(rpc_id, _JSONRPC_INTERNAL_ERROR, f"internal error: {exc}")


async def _handle_tools_call(
    *,
    rpc_id: Any,
    tool_name: str,
    arguments: dict[str, Any],
    ollama_url: str,
    timeout_seconds: float,
    http_post: Optional[Any],
    http_get: Optional[Any],
) -> dict[str, Any]:
    """Translate an MCP tools/call into the appropriate Ollama HTTP call."""
    post = http_post or _default_http_post
    get = http_get or _default_http_get

    if tool_name == "chat":
        model = arguments.get("model")
        messages = arguments.get("messages")
        if not model or not isinstance(messages, list):
            return _err(rpc_id, _JSONRPC_INVALID_PARAMS, "chat requires {model, messages}")
        if arguments.get("system"):
            messages = [{"role": "system", "content": str(arguments["system"])}, *messages]
        payload = {
            "model": str(model),
            "messages": messages,
            "stream": False,
            "options": {"temperature": float(arguments.get("temperature", 0.2))},
        }
        try:
            response = await post(f"{ollama_url}/api/chat", payload, timeout_seconds)
        except Exception as exc:
            return _err(
                rpc_id,
                _JSONRPC_OLLAMA_FAILED,
                f"ollama /api/chat failed: {exc}",
                data={"upstream_url": f"{ollama_url}/api/chat"},
            )
        text = _extract_chat_text(response)
        return _ok(rpc_id, {
            "content": [{"type": "text", "text": text}],
            "isError": False,
            "_meta": {"model": str(model), "ollama_response": _compact(response)},
        })

    if tool_name == "generate":
        model = arguments.get("model")
        prompt = arguments.get("prompt")
        if not model or not isinstance(prompt, str):
            return _err(rpc_id, _JSONRPC_INVALID_PARAMS, "generate requires {model, prompt}")
        payload = {
            "model": str(model),
            "prompt": str(prompt),
            "stream": False,
            "options": {"temperature": float(arguments.get("temperature", 0.2))},
        }
        if arguments.get("system"):
            payload["system"] = str(arguments["system"])
        try:
            response = await post(f"{ollama_url}/api/generate", payload, timeout_seconds)
        except Exception as exc:
            return _err(
                rpc_id,
                _JSONRPC_OLLAMA_FAILED,
                f"ollama /api/generate failed: {exc}",
                data={"upstream_url": f"{ollama_url}/api/generate"},
            )
        text = str(response.get("response") or "") if isinstance(response, dict) else ""
        return _ok(rpc_id, {
            "content": [{"type": "text", "text": text}],
            "isError": False,
            "_meta": {"model": str(model)},
        })

    if tool_name == "list_models":
        try:
            response = await get(f"{ollama_url}/api/tags", timeout_seconds)
        except Exception as exc:
            return _err(
                rpc_id,
                _JSONRPC_OLLAMA_FAILED,
                f"ollama /api/tags failed: {exc}",
            )
        models = response.get("models", []) if isinstance(response, dict) else []
        text = "\n".join(
            str(m.get("name", "")) for m in models if isinstance(m, dict)
        ) or "(no models pulled)"
        return _ok(rpc_id, {
            "content": [{"type": "text", "text": text}],
            "isError": False,
            "_meta": {"count": len(models)},
        })

    return _err(rpc_id, _JSONRPC_INVALID_PARAMS, f"unknown tool '{tool_name}'")


# ---------------------------------------------------------------------------
# HTTP client — aiohttp preferred, urllib fallback
# ---------------------------------------------------------------------------


async def _default_http_post(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    """POST JSON, return parsed JSON. Prefer aiohttp; fall back to stdlib."""
    try:
        import aiohttp  # type: ignore

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.post(url, json=payload) as resp:
                resp.raise_for_status()
                return await resp.json()
    except ImportError:
        return await _urllib_request(url, method="POST", payload=payload, timeout=timeout)


async def _default_http_get(url: str, timeout: float) -> dict[str, Any]:
    try:
        import aiohttp  # type: ignore

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            async with session.get(url) as resp:
                resp.raise_for_status()
                return await resp.json()
    except ImportError:
        return await _urllib_request(url, method="GET", payload=None, timeout=timeout)


async def _urllib_request(
    url: str,
    *,
    method: str,
    payload: Optional[dict[str, Any]],
    timeout: float,
) -> dict[str, Any]:
    """Stdlib fallback. Runs the blocking call off the loop."""
    import urllib.request

    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    def _do() -> dict[str, Any]:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    return await asyncio.get_running_loop().run_in_executor(None, _do)


# ---------------------------------------------------------------------------
# FastAPI app builder
# ---------------------------------------------------------------------------


def build_app():
    """Build a FastAPI app exposing ``POST /jsonrpc``.

    Imported lazily so this module can be loaded for unit tests without
    requiring FastAPI to be available.

    Implementation notes:

    * We declare the route handlers with ``response_class=JSONResponse``
      in the decorator and *no* return-type annotation on the handler.
      Some FastAPI versions interpret a ``-> JSONResponse`` annotation
      as the response_model and try to schema-validate the return
      value as a Pydantic model — it isn't one, so /openapi.json
      generation fails with 500 and route validation can produce
      misleading 422s on POST. Decorator-only response class avoids
      both pitfalls.
    * The route accepts the raw body via ``Body`` rather than
      ``Request.body()`` so FastAPI does the JSON parse + content-type
      negotiation itself. This also makes the openapi schema valid.
    """
    from fastapi import Body, FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="noetl-ollama-bridge", version="1.0")

    @app.post("/jsonrpc", response_class=JSONResponse)
    async def _jsonrpc(body: Any = Body(default=None)):
        # Body is parsed by FastAPI as either dict / list / scalar / None;
        # dispatch_jsonrpc tolerates anything (returns -32600 if not a
        # JSON-RPC envelope). We don't do our own try/except for parse
        # errors because FastAPI returns a clean 422 with details if
        # the wire bytes aren't JSON — same surface MCP clients expect.
        result = await dispatch_jsonrpc(body)
        return JSONResponse(result)

    @app.get("/healthz", response_class=JSONResponse)
    async def _healthz():  # pragma: no cover -- liveness probe
        return JSONResponse({"status": "ok"})

    return app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok(rpc_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


def _err(rpc_id: Any, code: int, message: str, *, data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": int(code), "message": str(message)}
    if data:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": err}


def _extract_chat_text(response: Any) -> str:
    """Pull the assistant content out of an Ollama /api/chat response.

    Ollama returns ``{message: {role: 'assistant', content: '...'}, ...}``
    on success; we tolerate older shapes that put the text at top-level
    or under ``response``.
    """
    if not isinstance(response, dict):
        return ""
    msg = response.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
    for key in ("content", "response", "text"):
        v = response.get(key)
        if isinstance(v, str):
            return v
    return ""


def _compact(response: Any) -> dict[str, Any]:
    """Return a small subset of the Ollama response for ``_meta``.

    Whole Ollama responses include the prompt eval timings + token counts
    that are useful for self-troubleshoot playbooks but bloat the wire.
    """
    if not isinstance(response, dict):
        return {}
    keep = (
        "model",
        "created_at",
        "done",
        "done_reason",
        "total_duration",
        "load_duration",
        "prompt_eval_count",
        "prompt_eval_duration",
        "eval_count",
        "eval_duration",
    )
    return {k: response[k] for k in keep if k in response}
