import os
import json
import time
import signal
import datetime
import uuid
import asyncio
import httpx
import socket
import contextlib
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, StrictUndefined, BaseLoader

from noetl.core.logger import setup_logger

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
    """Deregister server using stored name via HTTP (no DB fallback)."""
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

        server_url = _normalize_server_url(os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082'), ensure_api=True)
        try:
            resp = httpx.request(
                "DELETE",
                f"{server_url}/runtime/deregister",
                json={"name": name, "component_type": "server_api"},
                timeout=5.0,
            )
            logger.info(f"Server deregister response: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Server deregister HTTP error: {e}")

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
    """Attempt to deregister worker pool using stored name (HTTP only)."""
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

        try:
            resp = httpx.request(
                "DELETE",
                f"{server_url}/worker/pool/deregister",
                json={"name": name},
                timeout=5.0,
            )
            logger.info(f"Worker deregister response: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"Worker deregister HTTP error: {e}")

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
            deregister_on_exit: bool = True,
            register_on_init: bool = True,
    ) -> None:
        self.server_url = _normalize_server_url(
            server_url or os.getenv("NOETL_SERVER_URL", "http://localhost:8082"),
            ensure_api=True,
        )
        self.worker_id = worker_id or os.getenv("NOETL_WORKER_ID") or str(uuid.uuid4())
        self._jinja = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self._thread_pool = thread_pool or ThreadPoolExecutor(max_workers=4)
        self._process_pool = process_pool or ProcessPoolExecutor()
        self._deregister_on_exit = deregister_on_exit
        if register_on_init:
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
            logger.debug(f"WORKER: Completing job {job_id}")
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(f"{self.server_url}/queue/{job_id}/complete")
        except Exception:  # pragma: no cover - network best effort
            logger.debug("Failed to complete job %s", job_id, exc_info=True)

    async def _fail_job(self, job_id: int) -> None:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                # Do not retry failed jobs by default; mark terminal 'dead'
                await client.post(f"{self.server_url}/queue/{job_id}/fail", json={"retry": False})
        except Exception:  # pragma: no cover - network best effort
            logger.debug("Failed to mark job %s failed", job_id, exc_info=True)

    # ------------------------------------------------------------------
    # Job execution
    # ------------------------------------------------------------------
    def _execute_job_sync(self, job: Dict[str, Any]) -> None:
        action_cfg_raw = job.get("action")
        raw_context = job.get("context") or job.get("input_context") or {}
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
            # Base64 decoding is now handled in individual task executors
            # to ensure single method of code/command handling

            # Original task config merging logic (only when original_task_cfg exists)
            if isinstance(action_cfg, dict) and original_task_cfg:
                placeholder_codes = {"", "def main(**kwargs):\n    return {}"}
                if original_task_cfg.get('type') and action_cfg.get('type') in (None,
                                                                                'python') and original_task_cfg.get(
                        'type') not in (None, 'python'):
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
                                (isinstance(rendered_value,
                                            str) and '{{' in rendered_value and '}}' in rendered_value)):
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
            # Handle broker/maintenance jobs that are not standard task executions
            try:
                act_type = str(action_cfg.get('type') or '').strip().lower()
            except Exception:
                act_type = ''
            if act_type == 'result_aggregation':
                # Process loop result aggregation job via worker-side coroutine
                from noetl.plugin.result import process_loop_aggregation_job
                import asyncio as _a
                try:
                    _a.run(process_loop_aggregation_job(job))  # Python >=3.11 has asyncio.run alias
                except Exception:
                    # Compatible run for various environments
                    try:
                        _a.run(process_loop_aggregation_job(job))
                    except Exception:
                        loop = _a.new_event_loop()
                        try:
                            _a.set_event_loop(loop)
                            loop.run_until_complete(process_loop_aggregation_job(job))
                        finally:
                            try:
                                loop.close()
                            except Exception:
                                pass
                # Do not emit separate start/complete events here; the aggregation job emits its own
                return

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

            # Determine node_type for events (iterator vs task)
            node_type_val = "iterator" if act_type == "iterator" else "task"

            start_event = {
                "execution_id": execution_id,
                "event_type": "action_started",
                "status": "RUNNING",
                "node_id": node_id,
                "node_name": task_name,
                "node_type": node_type_val,
                "context": {"work": context, "task": action_cfg},
                "trace_component": {"worker_raw_context": raw_context},
                "timestamp": datetime.datetime.now().isoformat(),
            }
            if loop_meta:
                start_event.update(loop_meta)
            if parent_event_id:
                start_event["parent_event_id"] = parent_event_id
            
            from noetl.plugin import report_event
            report_event(start_event, self.server_url)

            try:
                # Normalize payloads: canonical 'data' with legacy aliases
                task_data = {}
                if isinstance(action_cfg, dict):
                    # Start from explicit data first
                    if isinstance(action_cfg.get('data'), dict):
                        task_data.update(action_cfg.get('data'))
                    # Merge legacy aliases with precedence: input > payload > with
                    try:
                        w = action_cfg.get('with') if isinstance(action_cfg.get('with'), dict) else None
                        if w:
                            task_data = {**w, **task_data}
                    except Exception:
                        pass
                    try:
                        p = action_cfg.get('payload') if isinstance(action_cfg.get('payload'), dict) else None
                        if p:
                            task_data = {**p, **task_data}
                    except Exception:
                        pass
                    try:
                        i = action_cfg.get('input') if isinstance(action_cfg.get('input'), dict) else None
                        if i:
                            task_data = {**i, **task_data}
                    except Exception:
                        pass
                if not isinstance(task_data, dict):
                    task_data = {}
                try:
                    exec_ctx = dict(context) if isinstance(context, dict) else {}
                except Exception:
                    exec_ctx = {}
                # Expose unified payload under exec_ctx['input'] for template convenience
                try:
                    if isinstance(exec_ctx, dict):
                        exec_ctx['input'] = dict(task_data)
                        exec_ctx['data'] = dict(task_data)
                except Exception:
                    pass
                try:
                    # Ensure execution_id is present and non-empty in context
                    if not exec_ctx.get('execution_id'):
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
                
                from noetl.plugin import execute_task
                result = execute_task(action_cfg, task_name, exec_ctx, self._jinja, task_data)

                # Inline save: if the action config declares a `save` block, perform the save on worker
                inline_save = None
                try:
                    inline_save = action_cfg.get('save') if isinstance(action_cfg, dict) else None
                except Exception:
                    inline_save = None
                if inline_save:
                    try:
                        # Provide current result to rendering context as `this` for convenience
                        try:
                            exec_ctx_with_result = dict(exec_ctx)
                            # Provide current step output as 'result' for inline save templates
                            _current = result.get('data') if isinstance(result, dict) and result.get('data') is not None else result
                            exec_ctx_with_result['result'] = _current
                            # Back-compat aliases
                            exec_ctx_with_result['this'] = result
                            if 'data' not in exec_ctx_with_result:
                                exec_ctx_with_result['data'] = _current
                            logger.debug(f"WORKER: Added result context variables - result keys: {list(_current.keys()) if isinstance(_current, dict) else type(_current)}, this keys: {list(result.keys()) if isinstance(result, dict) else type(result)}")
                        except Exception as ctx_err:
                            logger.warning(f"WORKER: Failed to add result context variables, falling back to original context: {ctx_err}")
                            exec_ctx_with_result = exec_ctx
                        from ..plugin.save import execute_save_task as _do_save
                        save_payload = {'save': inline_save}
                        logger.debug(f"WORKER: About to call save plugin with context keys: {list(exec_ctx_with_result.keys()) if isinstance(exec_ctx_with_result, dict) else type(exec_ctx_with_result)}")
                        if isinstance(exec_ctx_with_result, dict) and 'result' in exec_ctx_with_result:
                            logger.debug(f"WORKER: Context has 'result' of type: {type(exec_ctx_with_result['result'])}")
                        save_out = _do_save(save_payload, exec_ctx_with_result, self._jinja, task_data)
                        # Attach save outcome to result envelope under meta.save or data.save
                        if isinstance(result, dict):
                            if 'meta' in result and isinstance(result['meta'], dict):
                                result['meta']['save'] = save_out
                            else:
                                # Keep envelope valid; prefer adding under meta
                                result['meta'] = {'save': save_out}
                    except Exception as _e:
                        # Attach error under meta.save_error but do not fail the action
                        if isinstance(result, dict):
                            if 'meta' in result and isinstance(result['meta'], dict):
                                result['meta']['save_error'] = str(_e)
                            else:
                                result['meta'] = {'save_error': str(_e)}

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
                        "node_type": node_type_val,
                        "error": err_msg,
                        "traceback": tb_text,
                        "result": result,
                        "timestamp": datetime.datetime.now().isoformat(),
                    }
                    if loop_meta:
                        error_event.update(loop_meta)
                    if parent_event_id:
                        error_event["parent_event_id"] = parent_event_id
                    
                    from noetl.plugin import report_event
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
                        "node_type": node_type_val,
                        "result": result,
                        "timestamp": datetime.datetime.now().isoformat(),
                    }
                    if loop_meta:
                        complete_event.update(loop_meta)
                    if parent_event_id:
                        complete_event["parent_event_id"] = parent_event_id
                    
                    from noetl.plugin import report_event
                    report_event(complete_event, self.server_url)

                    # Emit a companion step_result event for easier querying of results per step
                    try:
                        norm_result = result
                        if isinstance(result, dict) and 'data' in result and result['data'] is not None:
                            norm_result = result['data']
                        step_result_event = {
                            "execution_id": execution_id,
                            "event_type": "step_result",
                            "status": "COMPLETED",
                            "node_id": node_id,
                            "node_name": task_name,
                            "node_type": node_type_val,
                            "result": norm_result,
                            "timestamp": datetime.datetime.now().isoformat(),
                        }
                        if loop_meta:
                            step_result_event.update(loop_meta)
                        if parent_event_id:
                            step_result_event["parent_event_id"] = parent_event_id
                        
                        from noetl.plugin import report_event
                        report_event(step_result_event, self.server_url)
                    except Exception:
                        logger.debug("WORKER: Failed to emit step_result companion event", exc_info=True)

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
                        "node_type": node_type_val,
                        "error": f"{type(e).__name__}: {str(e)}",
                        "traceback": tb_text,
                        "result": {"error": str(e), "traceback": tb_text},
                        "timestamp": datetime.datetime.now().isoformat(),
                    }
                    if loop_meta:
                        error_event.update(loop_meta)
                    if parent_event_id:
                        error_event["parent_event_id"] = parent_event_id
                    
                    from noetl.plugin import report_event
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
    async def _report_simple_worker_metrics(self) -> None:
        """Report simple worker metrics for standalone QueueWorker instances."""
        try:
            import psutil
            
            # Basic system metrics for standalone worker
            metrics_data = []
            
            try:
                # CPU and memory
                cpu_percent = psutil.cpu_percent(interval=0.1)
                memory = psutil.virtual_memory()
                process = psutil.Process()
                
                metrics_data.extend([
                    {
                        "metric_name": "noetl_system_cpu_usage_percent",
                        "metric_type": "gauge",
                        "metric_value": cpu_percent,
                        "help_text": "CPU usage percentage",
                        "unit": "percent"
                    },
                    {
                        "metric_name": "noetl_system_memory_usage_percent",
                        "metric_type": "gauge",
                        "metric_value": memory.percent,
                        "help_text": "Memory usage percentage",
                        "unit": "percent"
                    },
                    {
                        "metric_name": "noetl_worker_status",
                        "metric_type": "gauge",
                        "metric_value": 1,  # 1 = active
                        "help_text": "Worker status (1=active, 0=inactive)",
                        "unit": "status"
                    }
                ])
            except Exception as e:
                logger.debug(f"Error collecting worker metrics: {e}")
            
            # Get component name from environment or use worker_id
            component_name = os.environ.get('NOETL_WORKER_POOL_NAME') or f'worker-{self.worker_id}'
            
            # Report to server
            payload = {
                "component_name": component_name,
                "component_type": "queue_worker",
                "metrics": [
                    {
                        "metric_name": m.get("metric_name", ""),
                        "metric_type": m.get("metric_type", "gauge"),
                        "metric_value": m.get("metric_value", 0),
                        "timestamp": datetime.datetime.now().isoformat(),
                        "labels": {
                            "component": component_name,
                            "worker_id": self.worker_id,
                            "hostname": os.environ.get("HOSTNAME") or socket.gethostname()
                        },
                        "help_text": m.get("help_text", ""),
                        "unit": m.get("unit", "")
                    } for m in metrics_data
                ]
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.server_url}/metrics/report", json=payload)
                if resp.status_code != 200:
                    logger.debug(f"Worker metrics report failed {resp.status_code}: {resp.text}")
                    
        except Exception as e:
            logger.debug(f"Failed to report worker metrics: {e}")

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
        # Metrics reporting interval (default 60 seconds)
        metrics_interval = float(os.environ.get("NOETL_WORKER_METRICS_INTERVAL", "60"))
        last_metrics_time = 0.0
        
        try:
            while True:
                if stop_event and stop_event.is_set():
                    break
                    
                current_time = time.time()
                
                # Report metrics periodically
                if current_time - last_metrics_time >= metrics_interval:
                    try:
                        await self._report_simple_worker_metrics()
                        last_metrics_time = current_time
                    except Exception:
                        logger.debug("Worker metrics reporting failed", exc_info=True)
                
                job = await self._lease_job()
                if job:
                    await self._execute_job(job)
                else:
                    await asyncio.sleep(interval)
        finally:
            if self._deregister_on_exit:
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
        self.worker_id = os.getenv("NOETL_WORKER_ID") or str(uuid.uuid4())
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
            deregister_on_exit=False,
            register_on_init=False,
        )
        task = asyncio.create_task(
            worker.run_forever(self.worker_poll_interval, stop_evt)
        )
        self._tasks.append((task, stop_evt))

    async def _report_worker_metrics(self, component_name: str) -> None:
        """Report worker metrics to the server."""
        try:
            # Import here to avoid circular imports
            import psutil
            
            # Collect system metrics locally (based on metrics.py)
            metrics_data = []
            
            try:
                # CPU usage
                cpu_percent = psutil.cpu_percent(interval=0.1)
                metrics_data.append({
                    "metric_name": "noetl_system_cpu_usage_percent",
                    "metric_type": "gauge",
                    "metric_value": cpu_percent,
                    "help_text": "CPU usage percentage",
                    "unit": "percent"
                })
                
                # Memory usage
                memory = psutil.virtual_memory()
                metrics_data.append({
                    "metric_name": "noetl_system_memory_usage_bytes",
                    "metric_type": "gauge",
                    "metric_value": memory.used,
                    "help_text": "Memory usage in bytes",
                    "unit": "bytes"
                })
                
                metrics_data.append({
                    "metric_name": "noetl_system_memory_usage_percent",
                    "metric_type": "gauge",
                    "metric_value": memory.percent,
                    "help_text": "Memory usage percentage",
                    "unit": "percent"
                })
                
                # Process info
                process = psutil.Process()
                metrics_data.append({
                    "metric_name": "noetl_process_cpu_percent",
                    "metric_type": "gauge",
                    "metric_value": process.cpu_percent(),
                    "help_text": "Process CPU usage percentage",
                    "unit": "percent"
                })
                
                memory_info = process.memory_info()
                metrics_data.append({
                    "metric_name": "noetl_process_memory_rss_bytes",
                    "metric_type": "gauge",
                    "metric_value": memory_info.rss,
                    "help_text": "Process RSS memory in bytes",
                    "unit": "bytes"
                })
                
            except Exception as e:
                logger.debug(f"Error collecting system metrics: {e}")
            
            # Add worker-specific metrics
            metrics_data.extend([
                {
                    "metric_name": "noetl_worker_active_tasks",
                    "metric_type": "gauge", 
                    "metric_value": len(self._tasks),
                    "help_text": "Number of active worker tasks",
                    "unit": "tasks"
                },
                {
                    "metric_name": "noetl_worker_max_workers",
                    "metric_type": "gauge",
                    "metric_value": self.max_workers,
                    "help_text": "Maximum configured workers",
                    "unit": "workers"
                },
                {
                    "metric_name": "noetl_worker_queue_size",
                    "metric_type": "gauge", 
                    "metric_value": await self._queue_size(),
                    "help_text": "Current queue size",
                    "unit": "jobs"
                }
            ])
            
            # Report to server
            payload = {
                "component_name": component_name,
                "component_type": "worker_pool",
                "metrics": [
                    {
                        "metric_name": m.get("metric_name", ""),
                        "metric_type": m.get("metric_type", "gauge"),
                        "metric_value": m.get("metric_value", 0),
                        "timestamp": datetime.datetime.now().isoformat(),
                        "labels": {
                            "component": component_name,
                            "worker_id": self.worker_id,
                            "hostname": os.environ.get("HOSTNAME") or socket.gethostname()
                        },
                        "help_text": m.get("help_text", ""),
                        "unit": m.get("unit", "")
                    } for m in metrics_data
                ]
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{self.server_url}/metrics/report", json=payload)
                if resp.status_code != 200:
                    logger.debug(f"Metrics report failed {resp.status_code}: {resp.text}")
                    
        except Exception as e:
            logger.debug(f"Failed to report worker metrics: {e}")

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
        # Ensure single registration for the pool
        try:
            register_worker_pool_from_env()
        except Exception:
            logger.debug("Pool initial registration failed", exc_info=True)

        # Heartbeat loop task
        heartbeat_interval = float(os.environ.get("NOETL_WORKER_HEARTBEAT_INTERVAL", "15"))

        async def _heartbeat_loop():
            name = os.environ.get('NOETL_WORKER_POOL_NAME') or 'worker-cpu'
            payload = {"name": name}
            url = f"{self.server_url}/worker/pool/heartbeat"
            while not self._stop.is_set():
                try:
                    async with httpx.AsyncClient(timeout=5.0) as client:
                        resp = await client.post(url, json=payload)
                        if resp.status_code != 200:
                            logger.debug(f"Worker heartbeat non-200 {resp.status_code}: {resp.text}")
                    
                    # Report metrics with heartbeat
                    await self._report_worker_metrics(name)
                    
                except Exception:
                    logger.debug("Worker heartbeat/metrics failed", exc_info=True)
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
                with contextlib.suppress(Exception):
                    await hb_task
            except Exception:
                pass

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
