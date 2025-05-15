from fastapi import APIRouter, Depends, HTTPException
from noetl.api.services.gs import gs_upload
from noetl.api.schemas.gs import GoogleBucketStorageError
from noetl.util import setup_logger
from noetl.config.settings import AppConfig
from noetl.connectors.hub import get_connector_hub, ConnectorHub
logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()
router = APIRouter(prefix="/gs")

@router.post("/upload")
async def gs_upload(
        uri: str,
        local_file: str,
        context: ConnectorHub=Depends(get_connector_hub)
):
    try:
        return await gs_upload(gs_uri=uri, local_file=local_file, context=context)
    except GoogleBucketStorageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GS upload error: {str(e)}")


@router.post("/download")
async def gs_download(
        uri: str,
        local_file: str = None,
        context: ConnectorHub=Depends(get_connector_hub)
):
    try:
        return await gs_download(gs_uri=uri, local_file=local_file, context=context)
    except GoogleBucketStorageError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"GS download error: {str(e)}")
