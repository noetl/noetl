from __future__ import annotations

import asyncio
import contextlib
import uuid
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from typing import List, Optional, Tuple

from noetl.core.config import WorkerSettings
from noetl.core.logger import setup_logger

from .api_client import WorkerAPIClient
from .executors import create_process_pool_executor
from .queue_worker import QueueWorker
from .registry import (
    register_worker_pool_from_env,
    resolve_worker_settings,
)
from .utils import normalize_server_url

logger = setup_logger(__name__, include_location=True)


class ScalableQueueWorkerPool:
    """Pool that scales worker tasks based on queue depth."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        max_workers: Optional[int] = None,
        check_interval: float = 5.0,
        worker_poll_interval: float = 1.0,
        max_processes: Optional[int] = None,
        settings: Optional[WorkerSettings] = None,
    ) -> None:
        self._settings = resolve_worker_settings(settings)
        resolved_server_url = server_url or self._settings.normalized_server_url
        self.server_url = normalize_server_url(resolved_server_url, ensure_api=True)
        self.max_workers = max_workers or self._settings.max_workers
        self.check_interval = check_interval
        self.worker_poll_interval = worker_poll_interval
        self.max_processes = max_processes or self.max_workers
        self.worker_id = self._settings.worker_id or str(uuid.uuid4())
        self._thread_pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self._process_pool = create_process_pool_executor(self.max_processes)
        self._tasks: List[Tuple[asyncio.Task, asyncio.Event]] = []
        self._stop = asyncio.Event()
        self._stopped = False
        self._api = WorkerAPIClient(self._settings)

    async def _queue_size(self) -> int:
        return await self._api.queue_size()

    def _spawn_worker(self) -> None:
        stop_evt = asyncio.Event()
        worker = QueueWorker(
            self.server_url,
            thread_pool=self._thread_pool,
            process_pool=self._process_pool,
            deregister_on_exit=False,
            register_on_init=False,
            settings=self._settings,
            allow_process_pool_creation=self._process_pool is not None,
        )
        task = asyncio.create_task(
            worker.run_forever(self.worker_poll_interval, stop_evt)
        )
        self._tasks.append((task, stop_evt))

    async def _scale_workers(self) -> None:
        desired = min(self.max_workers, max(1, await self._queue_size()))
        current = len(self._tasks)
        if desired > current:
            for _ in range(desired - current):
                self._spawn_worker()
        elif desired < current:
            for _ in range(current - desired):
                task, evt = self._tasks.pop()
                evt.set()
                await task

    async def run_forever(self) -> None:
        registration_success = False
        try:
            register_worker_pool_from_env(self._settings)
            registration_success = True
            logger.info("Worker pool registration completed successfully")
        except Exception as exc:
            logger.exception(f"Pool initial registration failed: {exc}")

        if not registration_success:
            logger.info("Retrying worker pool registration...")
            try:
                register_worker_pool_from_env(self._settings)
                logger.info("Worker pool registration retry succeeded")
            except Exception as exc:
                logger.exception(f"Worker pool registration retry failed: {exc}")

        heartbeat_interval = self._settings.worker_heartbeat_interval

        async def _heartbeat_loop():
            name = (self._settings.pool_name or "").strip() or "worker-cpu"
            payload = {"name": name}
            consecutive_failures = 0
            max_failures = 5

            while not self._stop.is_set():
                success = await self._api.heartbeat(payload)
                if success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                    if consecutive_failures >= max_failures:
                        logger.exception(
                            f"Worker heartbeat failed {max_failures} consecutive times, continuing"
                        )
                        consecutive_failures = 0

                await asyncio.sleep(heartbeat_interval)

        hb_task = asyncio.create_task(_heartbeat_loop())
        try:
            while not self._stop.is_set():
                await self._scale_workers()
                await asyncio.sleep(self.check_interval)
        finally:
            await self.stop()
            try:
                hb_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await hb_task
            except Exception as exc:
                logger.exception(f"Error cancelling heartbeat task: {exc}")

    async def stop(self) -> None:
        """Request the scaling loop and all workers to stop."""
        if self._stopped:
            return
        self._stop.set()
        for task, evt in self._tasks:
            evt.set()
        await asyncio.gather(*(t for t, _ in self._tasks), return_exceptions=True)
        self._tasks.clear()
        self._thread_pool.shutdown(wait=False)
        if self._process_pool:
            self._process_pool.shutdown(wait=False)

        try:
            from noetl.plugin.tools.postgres.pool import close_all_plugin_pools

            await close_all_plugin_pools()
            logger.info("All plugin connection pools closed")
        except Exception as exc:
            logger.exception(f"Error closing plugin pools: {exc}")

        self._stopped = True
