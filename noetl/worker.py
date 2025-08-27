import os
import json
import time
import signal
import datetime
import uuid
import asyncio
import httpx
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, StrictUndefined, BaseLoader

from noetl.logger import setup_logger
from noetl.job import execute_task, execute_task_resolved, report_event

logger = setup_logger(__name__, include_location=True)


def register_worker_pool_from_env() -> None:
    """Register this worker pool with the server registry using environment variables.
    Required envs to trigger:
      - NOETL_WORKER_POOL_RUNTIME: cpu|gpu|qpu
      - NOETL_WORKER_BASE_URL: base URL where this worker exposes /api
    Optional:
      - NOETL_WORKER_POOL_NAME
      - NOETL_SERVER_URL (default http://localhost:8082)
      - NOETL_WORKER_CAPACITY
      - NOETL_WORKER_LABELS (CSV)
    """
    try:
        runtime = os.environ.get("NOETL_WORKER_POOL_RUNTIME", "").strip().lower()
        base_url = os.environ.get("NOETL_WORKER_BASE_URL", "").strip()
        if not runtime or not base_url:
            return
        name = os.environ.get("NOETL_WORKER_POOL_NAME") or f"worker-{runtime}"
        server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8082").rstrip('/')
        capacity = os.environ.get("NOETL_WORKER_CAPACITY")
        labels = os.environ.get("NOETL_WORKER_LABELS")
        if labels:
            labels = [s.strip() for s in labels.split(',') if s.strip()]
        payload = {
            "name": name,
            "runtime": runtime,
            "base_url": base_url,
            "status": "ready",
            "capacity": int(capacity) if capacity and str(capacity).isdigit() else None,
            "labels": labels,
            "pid": os.getpid(),
            "hostname": os.environ.get("HOSTNAME"),
        }
        url = f"{server_url}/api/worker/pool/register"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Worker pool registered: {name} ({runtime}) -> {base_url}")
                    try:
                        with open('/tmp/noetl_worker_pool_name', 'w') as f:
                            f.write(name)
                    except Exception:
                        pass
                else:
                    logger.warning(f"Worker pool register failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.warning(f"Worker pool register exception: {e}")
    except Exception:
        logger.exception("Unexpected error during worker pool registration")


def deregister_worker_pool_from_env() -> None:
    """Attempt to deregister worker pool using stored name (best-effort)."""
    try:
        name: Optional[str] = None
        if os.path.exists('/tmp/noetl_worker_pool_name'):
            try:
                with open('/tmp/noetl_worker_pool_name', 'r') as f:
                    name = f.read().strip()
            except Exception:
                name = None
        if not name:
            name = os.environ.get('NOETL_WORKER_POOL_NAME')
        if not name:
            return
        server_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
        try:
            with httpx.Client(timeout=5.0) as client:
                client.delete(f"{server_url}/api/worker/pool/deregister", json={"name": name})
            try:
                os.remove('/tmp/noetl_worker_pool_name')
            except Exception:
                pass
            logger.info(f"Deregistered worker pool: {name}")
        except Exception as e:
            logger.debug(f"Worker deregister attempt failed: {e}")
    except Exception:
        pass


def _on_worker_terminate(signum, frame):
    logger.info(f"Worker pool process received signal {signum}, attempting graceful deregister")
    try:
        retries = int(os.environ.get('NOETL_DEREGISTER_RETRIES', '3'))
        backoff_base = float(os.environ.get('NOETL_DEREGISTER_BACKOFF', '0.5'))
        for attempt in range(1, retries + 1):
            try:
                deregister_worker_pool_from_env()
                logger.info(f"Worker: deregister succeeded (attempt {attempt})")
                break
            except Exception as e:
                logger.debug(f"Worker: deregister attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
    finally:
        pass

try:
    signal.signal(signal.SIGTERM, _on_worker_terminate)
    signal.signal(signal.SIGINT, _on_worker_terminate)
except Exception:
    pass


def _get_server_url() -> str:
    return os.environ.get("NOETL_SERVER_URL", "http://localhost:8082/api")


# ------------------------------------------------------------------
# Queue worker pool implementation
# ------------------------------------------------------------------


class QueueWorker:
    """Async worker that polls the server queue API for actions."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        worker_id: Optional[str] = None,
        thread_pool: Optional[ThreadPoolExecutor] = None,
        process_pool: Optional[ProcessPoolExecutor] = None,
    ) -> None:
        self.server_url = (
            server_url or os.getenv("NOETL_SERVER_URL", "http://localhost:8082/api")
        ).rstrip("/")
        self.worker_id = worker_id or os.getenv("NOETL_WORKER_ID") or str(uuid.uuid4())
        self._jinja = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self._thread_pool = thread_pool or ThreadPoolExecutor(max_workers=4)
        self._process_pool = process_pool or ProcessPoolExecutor()
        self._register_pool()

    # ------------------------------------------------------------------
    # Queue interaction helpers
    # ------------------------------------------------------------------
    def _register_pool(self) -> None:
        """Best-effort registration of this worker pool."""
        try:
            register_worker_pool_from_env()
        except Exception:  # pragma: no cover - best effort
            logger.debug("Worker registration failed", exc_info=True)

    async def _lease_job(self, lease_seconds: int = 60) -> Optional[Dict[str, Any]]:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{self.server_url}/queue/lease",
                    json={"worker_id": self.worker_id, "lease_seconds": lease_seconds},
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") == "ok":
                    return data.get("job")
                return None
        except Exception:
            logger.debug("Failed to lease job", exc_info=True)
            return None

    async def _complete_job(self, job_id: int) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self.server_url}/queue/{job_id}/complete")
        except Exception:  # pragma: no cover - network best effort
            logger.debug("Failed to complete job %s", job_id, exc_info=True)

    async def _fail_job(self, job_id: int) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self.server_url}/queue/{job_id}/fail", json={})
        except Exception:  # pragma: no cover - network best effort
            logger.debug("Failed to mark job %s failed", job_id, exc_info=True)

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------
    def _execute_job_sync(self, job: Dict[str, Any]) -> None:
        action_cfg_raw = job.get("action")
        context = job.get("input_context") or {}
        execution_id = job.get("execution_id")
        node_id = job.get("node_id") or f"job_{job.get('id')}"

        # Parse action config if it's a JSON string
        if isinstance(action_cfg_raw, str):
            try:
                action_cfg = json.loads(action_cfg_raw)
            except json.JSONDecodeError:
                logger.error(f"Failed to parse action config for job {job.get('id')}: {action_cfg_raw}")
                return
        else:
            action_cfg = action_cfg_raw

        if isinstance(action_cfg, dict):
            task_name = action_cfg.get("name") or node_id

            # Emit action_started event
            start_event = {
                "execution_id": execution_id,
                "event_type": "action_started",
                "status": "RUNNING",
                "node_id": node_id,
                "node_name": task_name,
                "node_type": "task",
                "context": {"work": context, "task": action_cfg},
                "timestamp": datetime.datetime.now().isoformat(),
            }
            report_event(start_event, self.server_url)

            try:
                # Execute the task
                result = execute_task(action_cfg, task_name, context, self._jinja)

                # Emit action_completed event
                complete_event = {
                    "execution_id": execution_id,
                    "event_type": "action_completed",
                    "status": "COMPLETED",
                    "node_id": node_id,
                    "node_name": task_name,
                    "node_type": "task",
                    "result": result,
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                report_event(complete_event, self.server_url)

            except Exception as e:
                # Emit action_error event
                error_event = {
                    "execution_id": execution_id,
                    "event_type": "action_error",
                    "status": "ERROR",
                    "node_id": node_id,
                    "node_name": task_name,
                    "node_type": "task",
                    "error": str(e),
                    "result": {"error": str(e)},
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                report_event(error_event, self.server_url)
                raise  # Re-raise to let the worker handle job failure
        else:
            logger.warning("Job %s has no actionable configuration", job.get("id"))

    async def _execute_job(self, job: Dict[str, Any]) -> None:
        loop = asyncio.get_running_loop()
        use_process = bool(job.get("run_mode") == "process")
        executor = self._process_pool if use_process else self._thread_pool
        try:
            await loop.run_in_executor(executor, self._execute_job_sync, job)
            await self._complete_job(job["id"])
        except Exception as exc:  # pragma: no cover - network best effort
            logger.exception("Error executing job %s: %s", job.get("id"), exc)
            await self._fail_job(job["id"])

    # ------------------------------------------------------------------
    async def run_forever(
        self, interval: float = 1.0, stop_event: Optional[asyncio.Event] = None
    ) -> None:
        """Continuously poll for jobs and execute them asynchronously.

        Parameters
        ----------
        interval:
            Sleep duration between lease attempts when the queue is empty.
        stop_event:
            Optional :class:`asyncio.Event` that can be set by the caller to
            request the loop to exit.  This makes the worker usable inside
            pools where individual workers need to be stopped or replaced
            dynamically.
        """
        try:
            while True:
                if stop_event and stop_event.is_set():
                    break
                job = await self._lease_job()
                if job:
                    await self._execute_job(job)
                else:
                    await asyncio.sleep(interval)
        finally:  # pragma: no cover - cleanup on exit
            try:
                await asyncio.to_thread(deregister_worker_pool_from_env)
            except Exception:
                pass


class ScalableQueueWorkerPool:
    """Pool that scales worker tasks based on queue depth."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        max_workers: Optional[int] = None,
        check_interval: float = 5.0,
        worker_poll_interval: float = 1.0,
        max_processes: Optional[int] = None,
    ) -> None:
        self.server_url = (
            server_url or os.getenv("NOETL_SERVER_URL", "http://localhost:8082/api")
        ).rstrip("/")
        self.max_workers = max_workers or int(os.getenv("NOETL_MAX_WORKERS", "8"))
        self.check_interval = check_interval
        self.worker_poll_interval = worker_poll_interval
        self.max_processes = max_processes or self.max_workers
        self._thread_pool = ThreadPoolExecutor(max_workers=self.max_workers)
        self._process_pool = ProcessPoolExecutor(max_workers=self.max_processes)
        self._tasks: List[Tuple[asyncio.Task, asyncio.Event]] = []
        self._stop = asyncio.Event()
        self._stopped = False

    # --------------------------------------------------------------
    async def _queue_size(self) -> int:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.server_url}/queue/size")
                resp.raise_for_status()
                data = resp.json()
                return int(data.get("queued") or data.get("count") or 0)
        except Exception:  # pragma: no cover - network best effort
            logger.debug("Failed fetching queue size", exc_info=True)
            return 0

    def _spawn_worker(self) -> None:
        stop_evt = asyncio.Event()
        worker = QueueWorker(
            self.server_url,
            thread_pool=self._thread_pool,
            process_pool=self._process_pool,
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

    # --------------------------------------------------------------
    async def run_forever(self) -> None:
        """Run the auto-scaling loop until ``stop`` is called."""
        try:
            while not self._stop.is_set():
                await self._scale_workers()
                await asyncio.sleep(self.check_interval)
        finally:  # pragma: no cover - cleanup on exit
            await self.stop()

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
        self._process_pool.shutdown(wait=False)
        self._stopped = True
