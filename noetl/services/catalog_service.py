from noetl.schemas.catalog_schema import CatalogEntryResponse
from noetl.shared.connectors.postgrefy import pgsql_execute
from fastapi import HTTPException


class CatalogService:
    def register_entry(self, resource_path: str, resource_version: str, resource_type: str):
        try:
            query = """
            INSERT INTO catalog (resource_path, resource_type, resource_version, payload)
            VALUES (%s, %s, %s, '{}'::jsonb)
            """
            result = pgsql_execute(query, params=(resource_path, resource_type, resource_version))
            return CatalogEntryResponse(message="Resource registered successfully")
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
