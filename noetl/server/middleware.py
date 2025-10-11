import asyncio
import json
import time
from fastapi import Request, Response
from noetl.core.logger import logger

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


async def catch_exceptions_middleware(request: Request, call_next):
    start_time = time.time()
    request_json = await get_body(request)
    try:
        request_json = json.loads(request_json)
        request_json = json.dumps(request_json, indent=2)
    except Exception as err:
        pass
    try:
        response: Response = await asyncio.wait_for(call_next(request), timeout=1799.0)
        process_time_sec = time.time() - start_time
        # Read response body safely (handles both Response and StreamingResponse)
        response_body = b""
        async for chunk in response.body_iterator:
            response_body += chunk

        # Try parse JSON response
        try:
            response_json = json.loads(response_body)
            if "/openapi.json" in request.url.path:
                response_json = "valid openapi.json"
            response_json = json.dumps(response_json, indent=2)
        except Exception as err:
            response_json = response_body.decode()
        logger.info(f"{request.method} {request.url} ({round(process_time_sec, 2)}):\nrequest: {request_json}\nstatus_code: {response.status_code}\nresponse: {response_json}")
        # Rebuild response (since the original stream is consumed)
        new_response = Response(
            content=response_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )
        return new_response
    except asyncio.TimeoutError as err:
        process_time_sec = time.time() - start_time
        logger.error(f"{request.method} {request.url} ({round(process_time_sec, 2)}):\nrequest: {request_json}\nstatus_code: 504\nresponse: {err}")
        return Response(content="Request processing time exceeded the maximum timeout", status_code=504)
    except Exception as err:
        process_time_sec = time.time() - start_time
        logger.exception(f"{request.method} {request.url} ({round(process_time_sec, 2)}):\nrequest: {request_json}\nstatus_code: 500\nresponse: {err}")
        return Response(content=f"Detail: {err}", status_code=500)
