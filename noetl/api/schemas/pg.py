from pydantic import BaseModel
from typing import List, Any

class ProcedureCallRequest(BaseModel):
    proc_name: str
    args: List[str]

class SQLExecutionRequest(BaseModel):
    query: str
    params: List[Any] = []

class CSVExportRequest(BaseModel):
    query: str
    file_path: str
    uri_path: str | None
    schema_name: str = 'public'
    delimiter: str = ","
    headers: bool = True

class CSVImportRequest(BaseModel):
    table_name: str
    file_path: str
    uri_path: str | None
    schema_name: str = 'public'
    delimiter: str = ","
    headers: bool = True
    column_names: List[str] | None = None
