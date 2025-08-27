from typing import Any, Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from noetl.common import get_async_db_connection

router = APIRouter()


@router.post("/postgres/execute", response_class=JSONResponse)
async def execute_postgres(request: Request, query: str | None = None, query_base64: str | None = None, procedure: str | None = None, parameters: Any = None, schema: str | None = None, connection_string: str | None = None):
    body = await request.json()
    query = body.get("query") if body else query
    procedure = body.get("procedure") if body else procedure
    parameters = body.get("parameters") if body else parameters
    if not query and not procedure:
        return JSONResponse(content={"error": "query or procedure is required"}, status_code=400)
    try:
        async with get_async_db_connection(connection_string) as conn:
            async with conn.cursor() as cursor:
                if query:
                    await cursor.execute(query)
                    try:
                        result = await cursor.fetchall()
                    except Exception:
                        result = None
                elif procedure:
                    if isinstance(parameters, (list, tuple)):
                        await cursor.execute(procedure, parameters)
                    else:
                        await cursor.execute(procedure)
                    try:
                        result = await cursor.fetchall()
                    except Exception:
                        result = None
                try:
                    await conn.commit()
                except Exception:
                    pass
        return JSONResponse(content={"status": "ok", "result": result})
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
