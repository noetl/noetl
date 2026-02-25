import asyncio
import json
import os
import time
import logging
from fastapi import Request, Response
from noetl.core.logger import logger
from noetl.core.sanitize import sanitize_for_logging

# https://stackoverflow.com/questions/69669808/fastapi-custom-middleware-getting-body-of-request-inside

# set_body and get_body functions are used for unbloking getting body of request into next middlewares


async def set_body(request: Request, body: bytes):
    async def receive():
        return {"type": "http.request", "body": body}
    request._receive = receive


async def get_body(request: Request) -> bytes:
    body = await request.body()
    await set_body(request, body)
    return body


def _filter_paths(path: str, ignore: list[str]) -> bool:
    for substr in ignore:
        if substr in path:
            return True
    return False


def _payload_preview(raw_body: bytes, max_length: int = 1500) -> str:
    if not raw_body:
        return ""
    try:
        parsed = json.loads(raw_body)
        return sanitize_for_logging(parsed, max_length=max_length)
    except Exception:
        try:
            return sanitize_for_logging(raw_body.decode(errors="replace"), max_length=max_length)
        except Exception:
            return "<unavailable>"


def _payload_meta(raw_body: bytes) -> dict:
    meta = {"bytes": len(raw_body or b"")}
    if not raw_body:
        return meta

    try:
        parsed = json.loads(raw_body)
        if isinstance(parsed, dict):
            meta["kind"] = "object"
            meta["key_count"] = len(parsed)
            meta["keys"] = sorted(list(parsed.keys()))[:10]
        elif isinstance(parsed, list):
            meta["kind"] = "array"
            meta["items"] = len(parsed)
        else:
            meta["kind"] = type(parsed).__name__
    except Exception:
        meta["kind"] = "raw"
    return meta


async def catch_exceptions_middleware(request: Request, call_next):
    start_time = time.time()
    request_body = await get_body(request)
    ignore = [
        "heartbeat",
        "/api/executions"
    ]
    debug_logging_enabled = logger.isEnabledFor(logging.DEBUG)
    should_debug_log = debug_logging_enabled and not _filter_paths(request.url.path, ignore)
    include_error_payload = os.getenv(
        "NOETL_LOG_INCLUDE_PAYLOAD_ON_ERROR", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}

    try:
        response: Response = await asyncio.wait_for(call_next(request), timeout=1799.0)
        process_time_sec = time.time() - start_time

        # Keep fast path lightweight: only consume/rebuild the response body for debug previews.
        if not should_debug_log:
            return response

        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        logger.debug(
            "%s %s (%.2fs) status=%s request_meta=%s response_meta=%s",
            request.method,
            request.url,
            round(process_time_sec, 2),
            response.status_code,
            _payload_meta(request_body),
            {"kind": "openapi"} if "/openapi.json" in request.url.path else _payload_meta(response_body),
        )

        rebuilt_response = Response(
            content=response_body,
            status_code=response.status_code,
            media_type=response.media_type,
            background=response.background,
        )
        raw_headers = getattr(response, "raw_headers", None)
        if raw_headers is not None:
            # Preserve duplicate headers (e.g. multiple Set-Cookie) from the original response.
            rebuilt_response.raw_headers = [
                (k, v) for (k, v) in raw_headers if k.lower() != b"content-length"
            ]
            rebuilt_response.headers["content-length"] = str(len(response_body))
        else:
            for key, value in response.headers.items():
                rebuilt_response.headers[key] = value
        return rebuilt_response
    except asyncio.TimeoutError as err:
        process_time_sec = time.time() - start_time
        request_preview = (
            _payload_preview(request_body, max_length=800) if include_error_payload else "<omitted>"
        )
        logger.error(
            "%s %s (%.2fs) status=504 error=%s request_meta=%s request=%s",
            request.method,
            request.url,
            round(process_time_sec, 2),
            err,
            _payload_meta(request_body),
            request_preview,
        )
        return Response(content="Request processing time exceeded the maximum timeout", status_code=504)
    except Exception as err:
        process_time_sec = time.time() - start_time
        request_preview = (
            _payload_preview(request_body, max_length=800) if include_error_payload else "<omitted>"
        )
        logger.exception(
            "%s %s (%.2fs) status=500 error=%s request_meta=%s request=%s",
            request.method,
            request.url,
            round(process_time_sec, 2),
            err,
            _payload_meta(request_body),
            request_preview,
        )
        return Response(content=f"Detail: {err}", status_code=500)
