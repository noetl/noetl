import google.auth
from google.auth.transport.requests import Request as GoogleRequest
import httpx
from noetl.config.config import CloudConfig
from noetl.shared import setup_logger
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

class RequestHandler:
    def __init__(self, cloud_config: CloudConfig):
        if not cloud_config or not cloud_config.google_project or not cloud_config.google_region:
            raise ValueError("Missing required configuration in CloudConfig.")
        self.cloud_config = cloud_config
    @staticmethod
    async def request(
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
        if include_google_auth:
            credentials, _ = google.auth.default()
            credentials.refresh(GoogleRequest())
            headers["Authorization"] = f"Bearer {credentials.token}"

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

