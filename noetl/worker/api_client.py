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
