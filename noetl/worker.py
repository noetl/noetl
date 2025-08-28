import os
import json
import time
import signal
import datetime
import uuid
import asyncio
import httpx
import socket
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, StrictUndefined, BaseLoader

from noetl.logger import setup_logger
from noetl.job import execute_task, execute_task_resolved, report_event

logger = setup_logger(__name__, include_location=True)


def register_server_from_env() -> None:
    """Register this server instance with the server registry using environment variables.
    Required envs to trigger:
      - NOETL_SERVER_URL: server URL (will be auto-detected if not set)
    Optional:
      - NOETL_SERVER_NAME
      - NOETL_HOST (default localhost)
      - NOETL_PORT (default 8082)
      - NOETL_SERVER_LABELS (CSV)
    """
    try:
        server_url = os.environ.get("NOETL_SERVER_URL", "").strip()
        if not server_url:
            host = os.environ.get("NOETL_HOST", "localhost").strip()
            port = os.environ.get("NOETL_PORT", "8082").strip()
            server_url = f"http://{host}:{port}"
        
        if not server_url.endswith('/api'):
            server_url = server_url + '/api'
            
        name = os.environ.get("NOETL_SERVER_NAME") or f"server-{socket.gethostname()}"
        labels = os.environ.get("NOETL_SERVER_LABELS")
        if labels:
            labels = [s.strip() for s in labels.split(',') if s.strip()]
        
        # Get hostname with fallback
        hostname = os.environ.get("HOSTNAME") or socket.gethostname()
        
        payload = {
            "name": name,
            "component_type": "server_api",
            "runtime": "server",
            "base_url": server_url,
            "status": "ready",
            "capacity": None,
            "labels": labels,
            "pid": os.getpid(),
            "hostname": hostname,
        }
        
        url = f"{server_url}/runtime/register"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Server registered: {name} -> {server_url}")
                    try:
                        with open('/tmp/noetl_server_name', 'w') as f:
                            f.write(name)
                    except Exception:
                        pass
                else:
                    logger.warning(f"Server register failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            logger.warning(f"Server register exception: {e}")
    except Exception:
        logger.exception("Unexpected error during server registration")


def deregister_server_from_env() -> None:
    """Deregister server using stored name (best-effort)."""
    try:
        name: Optional[str] = None
        if os.path.exists('/tmp/noetl_server_name'):
            try:
                with open('/tmp/noetl_server_name', 'r') as f:
                    name = f.read().strip()
            except Exception:
                name = None
        if not name:
            name = os.environ.get('NOETL_SERVER_NAME')
        if not name:
            return
            
        logger.info(f"Attempting to deregister server {name} from database")
        try:
            from noetl.common import get_db_connection
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE runtime
                        SET status = 'offline', updated_at = now()
                        WHERE component_type = 'server_api' AND name = %s
                        """,
                        (name,)
                    )
                    conn.commit()
                    logger.info(f"Server {name} marked as offline in database")
        except Exception as db_e:
            logger.error(f"Database error during server deregistration: {db_e}")
        
        try:
            os.remove('/tmp/noetl_server_name')
        except Exception:
            pass
        logger.info(f"Deregistered server: {name}")
    except Exception:
        pass


def register_worker_pool_from_env() -> None:
    """Register this worker pool with the server registry using environment variables.
    Required envs to trigger:
      - NOETL_WORKER_POOL_RUNTIME: cpu|gpu|qpu
    Optional:
      - NOETL_WORKER_POOL_NAME
      - NOETL_SERVER_URL (default http://localhost:8082)
      - NOETL_WORKER_CAPACITY
      - NOETL_WORKER_LABELS (CSV)
      - NOETL_WORKER_BASE_URL (defaults to dummy value for queue-based workers)
    """
    try:
        runtime = os.environ.get("NOETL_WORKER_POOL_RUNTIME", "").strip().lower()
        if not runtime:
            return
        base_url = os.environ.get("NOETL_WORKER_BASE_URL", "http://queue-worker").strip()
        name = os.environ.get("NOETL_WORKER_POOL_NAME") or f"worker-{runtime}"
        server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8082").rstrip('/')
        if not server_url.endswith('/api'):
            server_url = server_url + '/api'
        capacity = os.environ.get("NOETL_WORKER_CAPACITY")
        labels = os.environ.get("NOETL_WORKER_LABELS")
        if labels:
            labels = [s.strip() for s in labels.split(',') if s.strip()]
        
        # Get hostname with fallback to socket.gethostname()
        hostname = os.environ.get("HOSTNAME") or socket.gethostname()
        
        payload = {
            "name": name,
            "runtime": runtime,
            "base_url": base_url,
            "status": "ready",
            "capacity": int(capacity) if capacity and str(capacity).isdigit() else None,
            "labels": labels,
            "pid": os.getpid(),
            "hostname": hostname,
        }
        url = f"{server_url}/worker/pool/register"
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(url, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Worker pool registered: {name} ({runtime}) -> {base_url}")
                    try:
                        with open(f'/tmp/noetl_worker_pool_name_{name}', 'w') as f:
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
    logger.info("Worker deregistration starting...")
    try:
        name: Optional[str] = None
        
        # First try to get name from environment
        name = os.environ.get('NOETL_WORKER_POOL_NAME')
        if name:
            logger.info(f"Using worker name from env: {name}")
            # Try worker-specific file first
            worker_file = f'/tmp/noetl_worker_pool_name_{name}'
            if os.path.exists(worker_file):
                try:
                    with open(worker_file, 'r') as f:
                        file_name = f.read().strip()
                    logger.info(f"Found worker name from file: {file_name}")
                    name = file_name
                except Exception:
                    pass
        
        # Fallback to old file for backward compatibility
        if not name and os.path.exists('/tmp/noetl_worker_pool_name'):
            try:
                with open('/tmp/noetl_worker_pool_name', 'r') as f:
                    name = f.read().strip()
                logger.info(f"Found worker name from legacy file: {name}")
            except Exception:
                name = None
                
        if not name:
            logger.warning("No worker name found for deregistration")
            return
        server_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082').rstrip('/')
        if not server_url.endswith('/api'):
            server_url = server_url + '/api'
        logger.info(f"Attempting to deregister worker {name} via {server_url}")

        # First try HTTP deregistration if server is reachable
        server_reachable = False
        try:
            health_url = server_url.replace('/api', '/health') if server_url.endswith('/api') else server_url + '/health'
            with httpx.Client(timeout=2.0) as client:
                resp = client.get(health_url)
                if resp.status_code == 200:
                    server_reachable = True
                    logger.info("Server is reachable, attempting HTTP deregistration")
                else:
                    logger.warning(f"Server health check failed with status {resp.status_code}")
        except Exception as e:
            logger.warning(f"Server health check failed: {e}")

        if server_reachable:
            try:
                import json
                resp = httpx.request(
                    "DELETE",
                    f"{server_url}/worker/pool/deregister",
                    data=json.dumps({"name": name}),
                    headers={"Content-Type": "application/json"},
                    timeout=5.0
                )
                logger.info(f"Worker deregister response: {resp.status_code} - {resp.text}")
                if resp.status_code == 200:
                    logger.info(f"HTTP deregistration successful for worker: {name}")
                else:
                    logger.warning(f"HTTP deregistration failed with status {resp.status_code}: {resp.text}")
            except Exception as e:
                logger.error(f"Worker deregister HTTP error: {e}")
        else:
            logger.info("Server not reachable, attempting direct database deregistration")
            # Fallback to direct database deregistration like the server does
            try:
                from noetl.common import get_db_connection
                with get_db_connection() as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            UPDATE noetl.runtime
                            SET status = 'offline', updated_at = now()
                            WHERE component_type = 'worker_pool' AND name = %s
                            """,
                            (name,)
                        )
                        conn.commit()
                        logger.info(f"Worker {name} marked as offline in database (direct)")
            except Exception as db_e:
                logger.error(f"Direct database deregistration failed: {db_e}")

        try:
            # Remove worker-specific file
            worker_file = f'/tmp/noetl_worker_pool_name_{name}'
            if os.path.exists(worker_file):
                os.remove(worker_file)
                logger.info("Removed worker-specific name file")
            # Also try to remove legacy file for backward compatibility
            elif os.path.exists('/tmp/noetl_worker_pool_name'):
                os.remove('/tmp/noetl_worker_pool_name')
                logger.info("Removed legacy worker name file")
        except Exception:
            pass
        logger.info(f"Deregistered worker pool: {name}")
    except Exception as e:
        logger.error(f"Worker deregister general error: {e}")


def _on_worker_terminate(signum, frame):
    logger.info(f"Worker pool process received signal {signum}")
    try:
        # Always try to deregister on exit
        retries = int(os.environ.get('NOETL_DEREGISTER_RETRIES', '3'))
        backoff_base = float(os.environ.get('NOETL_DEREGISTER_BACKOFF', '0.5'))
        for attempt in range(1, retries + 1):
            try:
                logger.info(f"Worker deregister attempt {attempt}")
                deregister_worker_pool_from_env()
                logger.info(f"Worker: deregister succeeded (attempt {attempt})")
                break
            except Exception as e:
                logger.error(f"Worker: deregister attempt {attempt} failed: {e}")
            if attempt < retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
    finally:
        logger.info("Worker termination signal handler completed")
        pass

try:
    signal.signal(signal.SIGTERM, _on_worker_terminate)
    signal.signal(signal.SIGINT, _on_worker_terminate)
except Exception:
    pass


def _get_server_url() -> str:
    server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8082").rstrip('/')
    if not server_url.endswith('/api'):
        server_url = server_url + '/api'
    return server_url


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
            server_url or os.getenv("NOETL_SERVER_URL", "http://localhost:8082")
        ).rstrip("/")
        if not self.server_url.endswith('/api'):
            self.server_url = self.server_url + '/api'
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
        raw_context = job.get("input_context") or {}
        # Server-side rendering: call server to render input context and task config
        # Worker must not render locally; prefer server-evaluated values
        context = raw_context
        rendered_task = None
        try:
            payload = {
                "execution_id": job.get("execution_id"),
                "template": {"work": raw_context, "task": action_cfg_raw},
                "extra_context": {
                    "env": dict(os.environ),
                    "job": {
                        "id": job.get("id"),
                        "execution_id": job.get("execution_id"),
                        "node_id": job.get("node_id"),
                        "worker_id": self.worker_id,
                    }
                },
                "strict": True
            }
            with httpx.Client(timeout=5.0) as client:
                resp = client.post(f"{self.server_url}/context/render", json=payload)
                if resp.status_code == 200:
                    rend = resp.json().get("rendered")
                    # Expecting a dict { work: <ctx>, task: <resolved_task> }
                    if isinstance(rend, dict):
                        if "work" in rend:
                            context = rend.get("work") or raw_context
                        # Capture server-resolved task config when provided
                        if "task" in rend:
                            rendered_task = rend.get("task")
                    elif isinstance(rend, dict):
                        context = rend
                else:
                    logger.warning(f"WORKER: server render failed {resp.status_code}: {resp.text}")
        except Exception:
            logger.debug("WORKER: server-side render exception; using raw context", exc_info=True)
            context = raw_context
        execution_id = job.get("execution_id")
        node_id = job.get("node_id") or f"job_{job.get('id')}"

        # If server returned a rendered task, use it; otherwise parse raw.
        # Fallback: if rendered is not a dict, try parsing raw JSON.
        action_cfg = None
        if rendered_task is not None and isinstance(rendered_task, dict):
            action_cfg = rendered_task
        else:
            # Parse action config if it's a JSON string
            if isinstance(action_cfg_raw, str):
                try:
                    action_cfg = json.loads(action_cfg_raw)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse action config for job {job.get('id')}: {action_cfg_raw}")
                    return
            elif isinstance(action_cfg_raw, dict):
                action_cfg = action_cfg_raw

        if isinstance(action_cfg, dict):
            task_name = action_cfg.get("name") or node_id

            # Emit action_started event
            logger.debug(f"WORKER: raw input_context: {json.dumps(raw_context, default=str)[:500]}")
            # Safety: default unresolved templated 'with' values to sensible fallbacks
            try:
                if isinstance(action_cfg.get('with'), dict):
                    safe_with = dict(action_cfg['with'])
                    for k, v in list(safe_with.items()):
                        if isinstance(v, str) and '{{' in v and '}}' in v:
                            if k in ('alerts', 'items', 'districts'):
                                safe_with[k] = '[]'
                            elif k == 'city':
                                # try to fall back to first city in context
                                c = None
                                try:
                                    wl = context if isinstance(context, dict) else {}
                                    cities = wl.get('cities') if isinstance(wl, dict) else None
                                    if isinstance(cities, list) and cities and isinstance(cities[0], dict):
                                        c = cities[0]
                                except Exception:
                                    c = None
                                safe_with[k] = c or {"name": "Unknown"}
                            elif k == 'district':
                                safe_with[k] = {"name": "Unknown"}
                    action_cfg['with'] = safe_with
            except Exception:
                pass

            try:
                logger.debug(f"WORKER: evaluated input_context (server): {json.dumps(context, default=str)[:500]}")
            except Exception:
                logger.debug("WORKER: evaluated input_context not JSON-serializable; using str()")
                logger.debug(f"WORKER: evaluated input_context (str): {str(context)[:500]}")
            loop_meta = None
            try:
                if isinstance(context, dict) and isinstance(context.get('_loop'), dict):
                    lm = context.get('_loop')
                    loop_meta = {
                        'loop_id': lm.get('loop_id'),
                        'loop_name': lm.get('loop_name'),
                        'iterator': lm.get('iterator'),
                        'current_index': lm.get('current_index'),
                        'current_item': lm.get('current_item'),
                        'items_count': lm.get('items_count'),
                    }
            except Exception:
                loop_meta = None

            start_event = { 
                "execution_id": execution_id,
                "event_type": "action_started",
                "status": "RUNNING",
                "node_id": node_id,
                "node_name": task_name,
                "node_type": "task",
                "context": {"work": context, "task": action_cfg},
                "trace_component": {"worker_raw_context": raw_context},
                "timestamp": datetime.datetime.now().isoformat(),
            }
            if loop_meta:
                start_event.update(loop_meta)
            report_event(start_event, self.server_url)

            try:
                # Execute the task
                task_with = action_cfg.get('with', {}) if isinstance(action_cfg, dict) else {}
                if not isinstance(task_with, dict):
                    task_with = {}
                result = execute_task(action_cfg, task_name, context, self._jinja, task_with)

                # Decide event type based on result status
                res_status = (result or {}).get('status', '') if isinstance(result, dict) else ''
                emitted_error = False
                if isinstance(res_status, str) and res_status.lower() == 'error':
                    # Emit action_error and raise to fail the job
                    err_msg = (result or {}).get('error') if isinstance(result, dict) else 'Unknown error'
                    tb_text = ''
                    if isinstance(result, dict):
                        tb_text = result.get('traceback') or ''
                    error_event = {
                        "execution_id": execution_id,
                        "event_type": "action_error",
                        "status": "ERROR",
                        "node_id": node_id,
                        "node_name": task_name,
                        "node_type": "task",
                        "error": err_msg,
                        "traceback": tb_text,
                        "result": result,
                        "timestamp": datetime.datetime.now().isoformat(),
                    }
                    report_event(error_event, self.server_url)
                    emitted_error = True
                    raise RuntimeError(err_msg or "Task returned error status")
                else:
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
                    if loop_meta:
                        complete_event.update(loop_meta)
                    report_event(complete_event, self.server_url)

            except Exception as e:
                # Emit action_error event with traceback (avoid duplicate if already emitted above)
                try:
                    import traceback as _tb
                    tb_text = _tb.format_exc()
                except Exception:
                    tb_text = str(e)
                if not locals().get('emitted_error'):
                    error_event = {
                        "execution_id": execution_id,
                        "event_type": "action_error",
                        "status": "ERROR",
                        "node_id": node_id,
                        "node_name": task_name,
                        "node_type": "task",
                        "error": f"{type(e).__name__}: {str(e)}",
                        "traceback": tb_text,
                        "result": {"error": str(e), "traceback": tb_text},
                        "timestamp": datetime.datetime.now().isoformat(),
                    }
                    if loop_meta:
                        error_event.update(loop_meta)
                    report_event(error_event, self.server_url)
                raise  # Re-raise to let the worker handle job failure
        else:
            logger.warning("Job %s has no actionable configuration", str(job.get("id")))

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
            server_url or os.getenv("NOETL_SERVER_URL", "http://localhost:8082")
        ).rstrip("/")
        if not self.server_url.endswith('/api'):
            self.server_url = self.server_url + '/api'
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
