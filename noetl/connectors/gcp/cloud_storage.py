import asyncio
import os
from google.cloud import storage
from noetl.config.settings import CloudConfig
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

def upload_blob(bucket_name: str, source_file_name: str, destination_blob_name: str, google_project: str):
    client = storage.Client(project=google_project or os.getenv("GCP_PROJECT"))
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_name)
    return blob.public_url

def parse_gs_uri(url: str):
    if url.startswith("gs://"):
        _, rest = url.split("gs://", 1)
        bucket_name, *object_path_parts = rest.split("/", 1)
        object_path = object_path_parts[0] if object_path_parts else ""
        return bucket_name, object_path
    return None, url

def get_gs_uri(uri: str, bucket_name: str = None) -> str:
    if uri.startswith("gs://"):
        return uri
    if bucket_name:
        bucket_prefix = "gs://" if not bucket_name.startswith("gs://") else ""
        return f"{bucket_prefix}{bucket_name}/{uri}"
    return uri

class GoogleStorageHandler:
    _buckets = {}

    def __init__(self, config: CloudConfig):
        self.client = storage.Client(project=config.google_project)

    def get_bucket(self, bucket_name: str):
        if bucket_name not in self._buckets:
            self._buckets[bucket_name] = self.client.bucket(bucket_name)
        return self._buckets.get(bucket_name)


    async def upload_stream(self, bucket_name: str, blob_name: str, data_stream):
        try:
            bucket = self.get_bucket(bucket_name)
            blob = bucket.blob(blob_name)
            logger.info(f"Uploading data stream to gs://{bucket_name}/{blob_name}.")

            async def generate():
                async for chunk in data_stream:
                    yield chunk.encode("utf-8")

            await asyncio.to_thread(blob.upload_from_file, generate(), content_type="text/csv")
            logger.info(f"Successfully uploaded stream to gs://{bucket_name}/{blob_name}")
        except Exception as err:
            logger.error(f"Failed to upload stream to gs://{bucket_name}/{blob_name}, error: {err}.")
            raise

    async def put(self, uri: str, content: bytes = None, local_path: str = None):
        try:
            bucket_name, object_path = parse_gs_uri(uri)
            bucket = self.get_bucket(bucket_name)
            blob = bucket.blob(object_path)
            if content is not None:
                await asyncio.to_thread(blob.upload_from_string, content, content_type="text/csv")
                logger.info(f"Google Storage uploaded {uri} from memory.")
            elif local_path:
                if not os.path.exists(local_path):
                    raise FileNotFoundError(f"Local file '{local_path}' not found.")

                await asyncio.to_thread(blob.upload_from_filename, local_path)
                logger.info(f"Google Storage uploaded {uri} from file: {local_path}.")
            else:
                raise ValueError("Either 'content' or 'local_path' must be provided.")

            return {"message": f"File uploaded to {uri}."}, 200

        except Exception as err:
            logger.error(f"Google Storage failed to upload {uri}: {err}.")
            return {"error": f"Google Storage upload failed: {str(err)}."}, 500


    async def get(self, uri: str):
        try:
            bucket_name, object_path = parse_gs_uri(uri)
            bucket = self.get_bucket(bucket_name)
            blob = bucket.blob(object_path)
            content = await asyncio.to_thread(blob.download_as_string)

            if not content:
                logger.error(f"Google Storage object {uri} is empty.")
                return {"error": f"Google Storage object {uri} is empty."}, 400

            logger.info(f"Object {uri} retrieved.", extra={"uri": uri})
            return content, 200

        except Exception as err:
            logger.error(f"Google Storage failed to get object {uri}, err: {err}.")
            return {"error": f"Google Storage object {uri} query failed {str(err)}."}, 500

    async def delete(self, uri: str):
        try:
            bucket_name, object_path = parse_gs_uri(uri)
            bucket = self.get_bucket(bucket_name)
            blob = bucket.blob(object_path)
            await asyncio.to_thread(blob.delete)
            logger.info(f"Google Storage object {uri} deleted.", extra={"uri": uri})
            return {"message": f"Google Storage object {uri} deleted."}, 200
        except Exception as err:
            logger.error(f"Google Storage failed to delete uri {uri}, err: {err}.")
            return {"error": f"Google Storage object {uri} delete failed {str(err)}."}, 500

    async def exists(self, uri: str):
        try:
            bucket_name, object_path = parse_gs_uri(uri)
            bucket = self.get_bucket(bucket_name)
            blob = bucket.blob(object_path)
            exists = await asyncio.to_thread(blob.exists)
            if exists:
                logger.info(f"Google Storage object {uri} exists.", extra={"uri": uri})
                return {"message": f"Google Storage object {uri} exists."}, 200
            else:
                logger.info(f"Google Storage object {uri} does not exist.", extra={"uri": uri})
                return {"message": f"Google Storage object {uri} does not exist."}, 404
        except Exception as err:
            logger.error(f"Google Storage failed to find uri {uri}, err: {err}.")
            return {"error": f"Google Storage object {uri} validation failed {str(err)}."}, 500
