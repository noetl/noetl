from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from noetl.core.config import WorkerSettings
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class WorkerAPIClient:
    """Thin asynchronous client around queue and worker endpoints."""

    def __init__(self, settings: WorkerSettings) -> None:
        self._settings = settings
        self._base_url = settings.server_api_url.rstrip("/")

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self._base_url}{path}"

    async def lease_job(
        self, worker_id: str, lease_seconds: int = 60
    ) -> Optional[Dict[str, Any]]:
        payload = {"worker_id": worker_id, "lease_seconds": lease_seconds}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(self._url("/queue/lease"), json=payload)
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "ok":
                    job = data.get("job")
                    if isinstance(job, dict):
                        return job
        except Exception:
            logger.debug("Failed to lease job", exc_info=True)
        return None

    async def complete_job(self, queue_id: int) -> None:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self._url(f"/queue/{queue_id}/complete"))
                response.raise_for_status()
                logger.debug("Successfully completed job %s", queue_id)
        except httpx.TimeoutException as exc:
            logger.error("Timeout completing job %s: %s", queue_id, exc, exc_info=True)
            raise
        except httpx.HTTPStatusError as exc:
            logger.error("HTTP error completing job %s (status %s): %s", queue_id, exc.response.status_code, exc, exc_info=True)
            raise
        except Exception as exc:
            logger.error("Failed to complete job %s: %s", queue_id, exc, exc_info=True)
            raise

    async def fail_job(
        self, queue_id: int, should_retry: bool, retry_delay_seconds: int
    ) -> None:
        payload = {"retry": should_retry, "retry_delay_seconds": retry_delay_seconds}
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self._url(f"/queue/{queue_id}/fail"), json=payload)
        except Exception as exc:
            logger.exception(f"Failed to mark job {queue_id} failed: {exc}")

    async def queue_size(self) -> int:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(self._url("/queue/size"))
                resp.raise_for_status()
                data = resp.json()
                return int(data.get("queued") or data.get("count") or 0)
        except Exception as exc:
            logger.exception(f"Failed fetching queue size: {exc}")
            return 0

    async def heartbeat(self, payload: Dict[str, Any]) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    self._url("/worker/pool/heartbeat"), json=payload
                )
                if resp.status_code != 200:
                    logger.warning(
                        "Worker heartbeat non-200 %s: %s", resp.status_code, resp.text
                    )
                    return False
                return True
        except Exception as exc:
            logger.exception(f"Worker heartbeat failed: {exc}")
            return False

    async def render_context(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # Increased timeout to 120s to accommodate complex template rendering
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(self._url("/context/render"), json=payload)
                resp.raise_for_status()
                rendered = resp.json().get("rendered")
                if isinstance(rendered, dict):
                    return rendered
        except Exception as exc:
            logger.exception(f"Server render failed: {exc}")
            raise

    async def fetch_catalog_id(self, execution_id: Optional[str]) -> Optional[str]:
        if not execution_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    self._url("/events"),
                    params={"execution_id": execution_id, "limit": 1},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    events = data.get("events")
                    if isinstance(events, list) and events:
                        first_event = events[0]
                        if isinstance(first_event, dict):
                            return first_event.get("catalog_id")
        except Exception as exc:
            logger.exception(f"Failed to fetch catalog_id for execution {execution_id}: {exc}")
        return None
