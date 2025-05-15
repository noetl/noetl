from fastapi import APIRouter,Depends, HTTPException
from noetl.api.schemas.pg import CSVExportRequest, CSVImportRequest
from noetl.api.services.pg import export_csv, import_csv
from noetl.util import setup_logger
from noetl.config.settings import AppConfig
from noetl.connectors.hub import get_connector_hub, ConnectorHub
from noetl.connectors.postgrefy import  parse_sql
from noetl.api.schemas.pg import ProcedureCallRequest, SQLExecutionRequest

logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
router = APIRouter(prefix="/pg")

@router.post("/csv/export")
async def export_pg_csv(req: CSVExportRequest, app_context: ConnectorHub = Depends(get_connector_hub)):
    return await export_csv(
        req.query,
        req.file_path,
        app_context,
        req.headers
    )

@router.post("/csv/import")
async def import_pg_csv(req: CSVImportRequest, app_context: ConnectorHub = Depends(get_connector_hub)):
    return await import_csv(
        req.table_name,
        req.file_path,
        app_context,
        req.schema_name,
        req.headers,
        req.column_names
    )

@router.post("/sql/execute")
async def sql_execute(request: SQLExecutionRequest, app_context: ConnectorHub=Depends(get_connector_hub)):
    try:
        query = request.query.strip()
        statement, args = parse_sql(query)
        logger.info(f"Statement: {statement}, Arguments: {args}")

        if not query:
            raise HTTPException(status_code=400, detail="SQL statement is missing.")

        result = await app_context.postgres.execute(statement, args)
        message = f"SQL command executed."
        logger.success(f"{message} Result: {result}", extra={"query": query})

        return {
            "status": "success",
            "message": message,
            "result": result,
        }

    except Exception as e:
        error_message = f"Error executing SQL/procedure '{request.query}': {e}"
        # traceback_details = traceback.format_exc()
        logger.error(error_message) # exc_info=True)

        raise HTTPException(
            status_code=500,
            detail={
                "error": error_message,
                "query": request.query
            }
        )
@router.post("/routine/call")
async def routine_call(
        request: ProcedureCallRequest,
        app_context:ConnectorHub =Depends(get_connector_hub)
):
    try:
        routine_name = request.routine_name
        args = request.args

        if not routine_name:
            raise ValueError("Routine name is missing.")

        logger.info(f"Calling routine '{routine_name}' with arguments: {args}")
        result = await app_context.postgres.call_routine(routine_name, tuple(args), is_procedure=True)

        return {
            "status": "success",
            "message": f"routine '{routine_name}' executed.",
            "result": result,
        }
    except Exception as e:
        logger.error(f"Error handling request '{request}': {e}")
        raise HTTPException(status_code=500, detail=f"Request '{request}' failed: {str(e)}")
