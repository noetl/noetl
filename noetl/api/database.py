from typing import Any, Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from noetl.common import get_async_db_connection
from psycopg.rows import dict_row

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


@router.get("/postgres/weather_alert_summary/{execution_id}/last", response_class=JSONResponse)
async def get_last_weather_alert_summary(request: Request, execution_id: str):
    """
    Return the last inserted row from public.weather_alert_summary for a given execution_id.
    """
    try:
        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    SELECT id, alert_cities, alert_count, execution_id, created_at
                    FROM public.weather_alert_summary
                    WHERE execution_id = %s
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (execution_id,)
                )
                row = await cur.fetchone()
                return JSONResponse(content={"status": "ok", "row": row})
    except Exception as e:
        return JSONResponse(content={"status": "error", "error": str(e)}, status_code=500)
