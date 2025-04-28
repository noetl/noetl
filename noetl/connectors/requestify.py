import os
import google.auth
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request as GoogleRequest
import httpx
from noetl.config.settings import CloudConfig
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

def evaluate_response(response: httpx.Response) -> dict:
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        body = {"error": "Response is not valid json.", "text": response.text}

    return {
        "status_code": status,
        "body": body,
    }

def load_google_credentials():
    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "/secrets/application_default_credentials.json")
    if not os.path.isfile(path):
        logger.warning(
            f"Google credentials not found at {path}.")
        return None
    try:
        credentials, _ = google.auth.default()
        credentials.refresh(GoogleRequest())
        logger.debug("Google credentials loaded.")
        return credentials
    except DefaultCredentialsError as e:
        logger.warning(f"Failed to load Google credentials: {e}.")
        return None


class RequestHandler:
    def __init__(self, cloud_config: CloudConfig):
        if not cloud_config or not cloud_config.google_project or not cloud_config.google_region:
            raise ValueError("Missing required configuration in CloudConfig.")
        self.cloud_config = cloud_config
        self.google_credentials = load_google_credentials()

    async def request(
            self,
            url: str,
            method: str = "POST",
            headers: dict = None,
            params: dict = None,
            json_data: dict = None,
            timeout: float = 60.0,
            include_google_auth: bool = False,
            verify: bool = True
    ) -> dict:
        headers = headers.copy() if headers else {}
        logger.debug(f"Request {method} {url}.")
        if include_google_auth and self.google_credentials:
            headers["Authorization"] = f"Bearer {self.google_credentials.token}"

        try:
            async with httpx.AsyncClient(verify=verify, timeout=timeout) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data
                )
        except httpx.RequestError as e:
            logger.error(f"Request error to {url}: {e}.")
            return {"status_code": None, "error": str(e)}
        return evaluate_response(response)

