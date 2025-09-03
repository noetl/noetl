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


def _normalize_server_url(url: Optional[str], ensure_api: bool = True) -> str:
    """Ensure server URL has http(s) scheme and optional '/api' suffix."""
    try:
        base = (url or "").strip()
        if not base:
            base = "http://localhost:8082"
        if not (base.startswith("http://") or base.startswith("https://")):
            base = "http://" + base
        base = base.rstrip('/')
        if ensure_api and not base.endswith('/api'):
            base = base + '/api'
        return base
    except Exception:
        return "http://localhost:8082/api" if ensure_api else "http://localhost:8082"

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
        server_url = _normalize_server_url(server_url, ensure_api=True)
            
        name = os.environ.get("NOETL_SERVER_NAME") or f"server-{socket.gethostname()}"
        labels = os.environ.get("NOETL_SERVER_LABELS")
        if labels:
            labels = [s.strip() for s in labels.split(',') if s.strip()]
        
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
        
        name = os.environ.get('NOETL_WORKER_POOL_NAME')
        if name:
            logger.info(f"Using worker name from env: {name}")
            worker_file = f'/tmp/noetl_worker_pool_name_{name}'
            if os.path.exists(worker_file):
                try:
                    with open(worker_file, 'r') as f:
                        file_name = f.read().strip()
                    logger.info(f"Found worker name from file: {file_name}")
                    name = file_name
                except Exception:
                    pass
        
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
        server_url = _normalize_server_url(os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082'), ensure_api=True)
        logger.info(f"Attempting to deregister worker {name} via {server_url}")

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
            worker_file = f'/tmp/noetl_worker_pool_name_{name}'
            if os.path.exists(worker_file):
                os.remove(worker_file)
                logger.info("Removed worker-specific name file")
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
    return _normalize_server_url(os.environ.get("NOETL_SERVER_URL", "http://localhost:8082"), ensure_api=True)


# ------------------------------------------------------------------
# Queue worker pool
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
        self.server_url = _normalize_server_url(
            server_url or os.getenv("NOETL_SERVER_URL", "http://localhost:8082"),
            ensure_api=True,
        )
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
                        # Provide uuid alias for templates expecting {{ job.uuid }}
                        "uuid": str(job.get("id")) if job.get("id") is not None else None,
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
        original_task_cfg = action_cfg_raw if isinstance(action_cfg_raw, dict) else None
        if rendered_task is not None and isinstance(rendered_task, dict):
            action_cfg = rendered_task
        else:
            if isinstance(action_cfg_raw, str):
                try:
                    action_cfg = json.loads(action_cfg_raw)
                except json.JSONDecodeError:
                    logger.error(f"Failed to parse action config for job {job.get('id')}: {action_cfg_raw}")
                    return
            elif isinstance(action_cfg_raw, dict):
                action_cfg = action_cfg_raw

        try:
            if isinstance(action_cfg, dict) and original_task_cfg:
                import base64
                if 'code_b64' in action_cfg:
                    try:
                        action_cfg['code'] = base64.b64decode(action_cfg['code_b64']).decode('utf-8')
                    except Exception:
                        logger.debug("WORKER: Failed to decode code_b64", exc_info=True)
                for field in ('command', 'commands'):
                    b64_key = f"{field}_b64"
                    if b64_key in action_cfg:
                        try:
                            decoded = base64.b64decode(action_cfg[b64_key]).decode('utf-8')
                            action_cfg[field] = decoded
                        except Exception:
                            logger.debug(f"WORKER: Failed to decode {b64_key}", exc_info=True)
                placeholder_codes = {"", "def main(**kwargs):\n    return {}"}
                if original_task_cfg.get('type') and action_cfg.get('type') in (None, 'python') and original_task_cfg.get('type') not in (None, 'python'):
                    action_cfg['type'] = original_task_cfg.get('type')
                if 'code' in original_task_cfg:
                    rendered_code = action_cfg.get('code')
                    if (rendered_code in placeholder_codes or 
                        'code' not in action_cfg or
                        (isinstance(rendered_code, str) and '{{' in rendered_code and '}}' in rendered_code)):
                        action_cfg['code'] = original_task_cfg['code']
                for field in ('command', 'commands'):
                    if field in original_task_cfg:
                        rendered_value = action_cfg.get(field)
                        if (field not in action_cfg or 
                            not rendered_value or 
                            (isinstance(rendered_value, str) and '{{' in rendered_value and '}}' in rendered_value)):
                            action_cfg[field] = original_task_cfg[field]
                if isinstance(original_task_cfg.get('with'), dict):
                    merged_with = {}
                    merged_with.update(original_task_cfg.get('with') or {})
                    if isinstance(action_cfg.get('with'), dict):
                        merged_with.update(action_cfg.get('with') or {})
                    action_cfg['with'] = merged_with
        except Exception:
            logger.debug("WORKER: Failed to merge original task config after server render", exc_info=True)

        if isinstance(action_cfg, dict):
            task_name = action_cfg.get("name") or node_id

            logger.debug(f"WORKER: raw input_context: {json.dumps(raw_context, default=str)[:500]}")
            try:
                if not isinstance(action_cfg.get('with'), dict):
                    action_cfg['with'] = {}
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

            # Extract parent_event_id from context metadata when provided (e.g., loop iteration parent)
            parent_event_id = None
            try:
                if isinstance(context, dict):
                    meta = context.get('_meta') or {}
                    if isinstance(meta, dict):
                        peid = meta.get('parent_event_id')
                        if peid:
                            parent_event_id = peid
            except Exception:
                parent_event_id = None

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
            if parent_event_id:
                start_event["parent_event_id"] = parent_event_id
            report_event(start_event, self.server_url)

            try:
                task_with = action_cfg.get('with', {}) if isinstance(action_cfg, dict) else {}
                if not isinstance(task_with, dict):
                    task_with = {}
                try:
                    exec_ctx = dict(context) if isinstance(context, dict) else {}
                except Exception:
                    exec_ctx = {}
                try:
                    if 'execution_id' not in exec_ctx:
                        exec_ctx['execution_id'] = execution_id
                except Exception:
                    pass
                try:
                    if 'env' not in exec_ctx:
                        exec_ctx['env'] = dict(os.environ)
                except Exception:
                    pass
                try:
                    if 'job' not in exec_ctx:
                        exec_ctx['job'] = {
                            'id': job.get('id'),
                            'uuid': str(job.get('id')) if job.get('id') is not None else None,
                            'execution_id': job.get('execution_id'),
                            'node_id': node_id,
                            'worker_id': self.worker_id,
                        }
                except Exception:
                    pass
                result = execute_task(action_cfg, task_name, exec_ctx, self._jinja, task_with)

                res_status = (result or {}).get('status', '') if isinstance(result, dict) else ''
                emitted_error = False
                if isinstance(res_status, str) and res_status.lower() == 'error':
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
                    if loop_meta:
                        error_event.update(loop_meta)
                    if parent_event_id:
                        error_event["parent_event_id"] = parent_event_id
                    report_event(error_event, self.server_url)
                    emitted_error = True
                    raise RuntimeError(err_msg or "Task returned error status")
                else:
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
                    if parent_event_id:
                        complete_event["parent_event_id"] = parent_event_id
                    report_event(complete_event, self.server_url)

            except Exception as e:
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
                    if parent_event_id:
                        error_event["parent_event_id"] = parent_event_id
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
        except Exception as exc:
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
        finally:
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
        self.server_url = _normalize_server_url(
            server_url or os.getenv("NOETL_SERVER_URL", "http://localhost:8082"),
            ensure_api=True,
        )
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
        finally:
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
