import aiofiles
from fastapi import HTTPException
import os
from noetl.api.schemas.gs import GoogleBucketStorageError
from noetl.util.env import mkdir
from noetl.config.settings import AppConfig
from noetl.connectors.hub import ConnectorHub
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)
app_config = AppConfig()


async def gs_upload(gs_uri: str, blob: str, local_file: str, context: ConnectorHub):
    try:
        if not os.path.exists(local_file):
            raise FileNotFoundError(f"Local file '{local_file}' not found.")
        await context.gs.put(uri=gs_uri, content=open(local_file, "rb").read())

        logger.success(f"File {local_file} uploaded to: {gs_uri}")
        return {"status": "success", "message": f"File uploaded to {gs_uri}"}

    except FileNotFoundError as e:
        logger.error(f"Upload failed - File not found: {local_file}")
        raise HTTPException(status_code=404, detail=f"File not found: {local_file}")

    except Exception as e:
        logger.error(f"Upload failed - Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload file: {str(e)}")


async def gs_download(gs_uri: str, local_file: str, context):
    try:
        logger.info(f"Starting download: {gs_uri}")
        await mkdir(os.path.dirname(local_file))
        content, status_code = await context.gs.get(uri=gs_uri)

        if status_code == 200:
            async with aiofiles.open(local_file, "wb") as file:
                await file.write(content)
            logger.success(f"Blob {gs_uri}  saved to {local_file}")
            return {"status": "success", "message": f"File {gs_uri} saved to {local_file}"}
        else:
            logger.error(f"Download failed: {content.get('error', 'Unknown error')}")
            raise GoogleBucketStorageError(message=content.get("error", "Unknown error occurred"),
                                           status_code=status_code)
    except Exception as e:
        logger.error(f"Failed to download file: {str(e)}")
        raise GoogleBucketStorageError(message=f"Failed to download file: {str(e)}", status_code=500)
