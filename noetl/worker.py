import os
import json
import time
import signal
import datetime
from typing import Dict, Any, Optional

from jinja2 import Environment, StrictUndefined, BaseLoader
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from noetl.logger import setup_logger
from noetl.action import execute_task, execute_task_resolved, report_event

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
            import requests
            resp = requests.post(url, json=payload, timeout=5.0)
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
            import requests
            requests.delete(f"{server_url}/api/worker/pool/deregister", json={"name": name}, timeout=5.0)
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

# ===== Worker pool API router =====

router = APIRouter()


def _get_server_url() -> str:
    return os.environ.get("NOETL_SERVER_URL", "http://localhost:8082/api")


@router.get("/health", include_in_schema=False)
async def worker_health():
    return {"status": "ok", "component": "worker"}


@router.post("/worker/action")
async def worker_run_action(request: Request, background_tasks: BackgroundTasks):
    """
    Execute a single action (task) in isolated mode using BackgroundTasks.
    Expected body:
    {
      "execution_id": "...",                 # required
      "parent_event_id": "...",              # optional
      "node_id": "step1.task1",              # optional info
      "node_name": "http_call",              # optional info
      "node_type": "task",                   # optional info
      "context": { ... },                      # optional context dict
      "mock_mode": false,                      # optional, default False
      "task": {                                # required task config as in playbook
         "name": "http_call",
         "type": "http",
         "config": { ... }
      }
    }
    """
    try:
        body: Dict[str, Any] = await request.json()
        execution_id = body.get("execution_id")
        if not execution_id:
            raise HTTPException(status_code=400, detail="execution_id is required")
        task_cfg = body.get("task")
        if not task_cfg or not isinstance(task_cfg, dict):
            raise HTTPException(status_code=400, detail="task is required and must be an object")
        context = body.get("context") or {}
        parent_event_id = body.get("parent_event_id")
        node_id = body.get("node_id") or task_cfg.get("name") or f"task_{os.urandom(4).hex()}"
        node_name = body.get("node_name") or task_cfg.get("name") or "task"
        node_type = body.get("node_type") or "task"
        mock_mode = bool(body.get("mock_mode", False))

        server_url = _get_server_url()

        start_event = {
            "execution_id": execution_id,
            "parent_event_id": parent_event_id,
            "event_type": "action_started",
            "status": "RUNNING",
            "node_id": node_id,
            "node_name": node_name,
            "node_type": node_type,
            "context": {"work": context, "task": task_cfg},
            "timestamp": datetime.datetime.now().isoformat(),
        }
        start_evt = report_event(start_event, server_url)

        def _run_action_background():
            try:
                jenv = Environment(loader=BaseLoader(), undefined=StrictUndefined)
                jenv.filters['to_json'] = lambda obj: json.dumps(obj)
                jenv.filters['b64encode'] = lambda s: __import__('base64').b64encode(s.encode('utf-8')).decode('utf-8') if isinstance(s, str) else __import__('base64').b64encode(str(s).encode('utf-8')).decode('utf-8')
                jenv.globals['now'] = lambda: datetime.datetime.now().isoformat()
                jenv.globals['env'] = os.environ

                if bool(body.get("resolved", False)):
                    result = execute_task_resolved(task_config=task_cfg, task_name=(task_cfg.get("name") or node_name), context=context or {}, jinja_env=jenv)  # type: ignore
                else:
                    result = execute_task(jenv, task_cfg, context or {}, mock_mode=mock_mode)  # type: ignore
                complete_event = {
                    "event_id": (start_evt or {}).get("event_id"),
                    "execution_id": execution_id,
                    "parent_event_id": parent_event_id,
                    "event_type": "action_completed",
                    "status": "COMPLETED",
                    "node_id": node_id,
                    "node_name": node_name,
                    "node_type": node_type,
                    "result": result,
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                report_event(complete_event, server_url)
            except Exception as e:
                error_event = {
                    "event_id": (start_evt or {}).get("event_id"),
                    "execution_id": execution_id,
                    "parent_event_id": parent_event_id,
                    "event_type": "action_error",
                    "status": "ERROR",
                    "node_id": node_id,
                    "node_name": node_name,
                    "node_type": node_type,
                    "error": str(e),
                    "result": {"error": str(e)},
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                report_event(error_event, server_url)

        background_tasks.add_task(_run_action_background)
        return {"status": "accepted", "message": "Action scheduled", "execution_id": execution_id, "event_id": (start_evt or {}).get("event_id")}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Worker error scheduling action: {e}")
        raise HTTPException(status_code=500, detail=str(e))
