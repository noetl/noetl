import asyncio
import concurrent.futures
import copy
import json
import logging
import os
import queue
import signal
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from multiprocessing import Process, Queue as MPQueue
from typing import Any, Dict, List, Optional

import jinja2
import psycopg
import requests
from psycopg.rows import dict_row

from noetl.core.common import get_db_connection, get_snowflake_id
from noetl.core.config import get_settings
from noetl.core.logger import setup_logger
from noetl.job.job import execute_job

logger = setup_logger(__name__, include_location=True)


def _normalize_server_url(server_url: str) -> str:
    """Normalize server URL to ensure it ends with /api"""
    server_url = server_url.strip()
    if not server_url:
        raise ValueError("Server URL cannot be empty")

    # Remove trailing slash if present
    if server_url.endswith('/'):
        server_url = server_url[:-1]

    # Add /api if not already present
    if not server_url.endswith('/api'):
        server_url = server_url + '/api'

    return server_url


def register_server_from_env() -> None:
    """Register server runtime using environment variables."""
    server_url = os.environ.get("NOETL_SERVER_URL", "").strip()
    if not server_url:
        raise RuntimeError("NOETL_SERVER_URL environment variable is required but not set")

    server_url = _normalize_server_url(server_url)

    name = os.environ.get("NOETL_SERVER_NAME", "").strip()
    if not name:
        raise RuntimeError("NOETL_SERVER_NAME environment variable is required but not set")

    labels_env = os.environ.get("NOETL_SERVER_LABELS")
    if labels_env:
        labels = [s.strip() for s in labels_env.split(',') if s.strip()]
    else:
        labels = None

    hostname = os.environ.get("HOSTNAME") or socket.gethostname()

    try:
        rid = get_snowflake_id()
    except Exception:
        import datetime as _dt
        rid = int(_dt.datetime.now().timestamp() * 1000)

    payload_runtime = {
        "type": "server",
        "pid": os.getpid(),
        "hostname": hostname,
    }

    labels_json = json.dumps(labels) if labels is not None else None
    runtime_json = json.dumps(payload_runtime)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO runtime (runtime_id, name, component_type, base_url, status, labels, capacity, runtime, last_heartbeat, created_at, updated_at)
                VALUES (%s, %s, 'server_api', %s, 'ready', %s, NULL, %s, now(), now(), now())
                ON CONFLICT (component_type, name)
                DO UPDATE SET
                    base_url = EXCLUDED.base_url,
                    status = EXCLUDED.status,
                    labels = EXCLUDED.labels,
                    runtime = EXCLUDED.runtime,
                    last_heartbeat = now(),
                    updated_at = now()
                """,
                (rid, name, server_url, labels_json, runtime_json)
            )
            conn.commit()

    # Store server name for cleanup
    try:
        with open('/tmp/noetl_server_name', 'w') as f:
            f.write(name)
    except Exception:
        pass

    logger.info(f"Registered server runtime: {name} at {server_url}")


def deregister_server_from_env() -> None:
    """Deregister server runtime using environment variables."""
    name = os.environ.get("NOETL_SERVER_NAME", "").strip()
    if not name:
        # Try to read from temp file
        try:
            with open('/tmp/noetl_server_name', 'r') as f:
                name = f.read().strip()
        except Exception:
            name = None

    if not name:
        logger.warning("Cannot deregister server: NOETL_SERVER_NAME not set and no temp file found")
        return

    try:
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

        logger.info(f"Deregistered server runtime: {name}")

        # Clean up temp file
        try:
            os.unlink('/tmp/noetl_server_name')
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Failed to deregister server runtime {name}: {e}")


def register_worker_pool_from_env() -> None:
    """Register worker pool runtime using environment variables."""
    server_url = os.environ.get("NOETL_SERVER_URL", "").strip()
    if not server_url:
        raise RuntimeError("NOETL_SERVER_URL environment variable is required but not set")

    server_url = _normalize_server_url(server_url)

    name = os.environ.get("NOETL_WORKER_POOL_NAME", "").strip()
    if not name:
        raise RuntimeError("NOETL_WORKER_POOL_NAME environment variable is required but not set")

    labels_env = os.environ.get("NOETL_WORKER_POOL_LABELS")
    if labels_env:
        labels = [s.strip() for s in labels_env.split(',') if s.strip()]
    else:
        labels = None

    capacity = int(os.environ.get("NOETL_WORKER_POOL_CAPACITY", "1"))
    hostname = os.environ.get("HOSTNAME") or socket.gethostname()

    try:
        rid = get_snowflake_id()
    except Exception:
        import datetime as _dt
        rid = int(_dt.datetime.now().timestamp() * 1000)

    payload_runtime = {
        "type": "worker_pool",
        "pid": os.getpid(),
        "hostname": hostname,
        "capacity": capacity,
    }

    labels_json = json.dumps(labels) if labels is not None else None
    runtime_json = json.dumps(payload_runtime)

    with get_db_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO runtime (runtime_id, name, component_type, base_url, status, labels, capacity, runtime, last_heartbeat, created_at, updated_at)
                VALUES (%s, %s, 'worker_pool', %s, 'ready', %s, %s, %s, now(), now(), now())
                ON CONFLICT (component_type, name)
                DO UPDATE SET
                    base_url = EXCLUDED.base_url,
                    status = EXCLUDED.status,
                    labels = EXCLUDED.labels,
                    capacity = EXCLUDED.capacity,
                    runtime = EXCLUDED.runtime,
                    last_heartbeat = now(),
                    updated_at = now()
                """,
                (rid, name, server_url, labels_json, capacity, runtime_json)
            )
            conn.commit()

    # Store worker pool name for cleanup
    try:
        with open('/tmp/noetl_worker_pool_name', 'w') as f:
            f.write(name)
    except Exception:
        pass

    logger.info(f"Registered worker pool runtime: {name} with capacity {capacity}")


def deregister_worker_pool_from_env() -> None:
    """Deregister worker pool runtime using environment variables."""
    name = os.environ.get("NOETL_WORKER_POOL_NAME", "").strip()
    if not name:
        # Try to read from temp file
        try:
            with open('/tmp/noetl_worker_pool_name', 'r') as f:
                name = f.read().strip()
        except Exception:
            name = None

    if not name:
        logger.warning("Cannot deregister worker pool: NOETL_WORKER_POOL_NAME not set and no temp file found")
        return

    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                # Mark all workers in this pool as offline first
                cursor.execute(
                    """
                    UPDATE runtime
                    SET status = 'offline', updated_at = now()
                    WHERE component_type = 'worker' 
                    AND JSON_EXTRACT(runtime, '$.pool_name') = %s
                    """,
                    (name,)
                )

                # Mark the pool itself as offline
                cursor.execute(
                    """
                    UPDATE runtime
                    SET status = 'offline', updated_at = now()
                    WHERE component_type = 'worker_pool' AND name = %s
                    """,
                    (name,)
                )
                conn.commit()

        logger.info(f"Deregistered worker pool runtime: {name}")

        # Clean up temp file
        try:
            os.unlink('/tmp/noetl_worker_pool_name')
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Failed to deregister worker pool runtime {name}: {e}")


def _on_worker_terminate(worker_id: str, pool_name: str) -> None:
    """Handle worker termination by updating its status in the database."""
    try:
        with get_db_connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE runtime
                    SET status = 'offline', updated_at = now()
                    WHERE component_type = 'worker' AND name = %s
                    """,
                    (worker_id,)
                )
                conn.commit()
        logger.debug(f"Marked worker {worker_id} as offline in pool {pool_name}")
    except Exception as e:
        logger.error(f"Failed to update worker {worker_id} status on termination: {e}")


def _get_server_url() -> str:
    """Get server URL from environment or settings."""
    server_url = os.environ.get("NOETL_SERVER_URL", "").strip()
    if not server_url:
        try:
            settings = get_settings()
            server_url = getattr(settings, 'server_url', '').strip()
        except Exception:
            pass

    if not server_url:
        raise RuntimeError("Server URL not found in environment or settings")

    return _normalize_server_url(server_url)


class QueueWorker:
    """A worker that processes jobs from a queue."""

    def __init__(
        self, 
        server_url: Optional[str] = None,
        worker_id: Optional[str] = None,
        max_workers: int = 4,
        max_processes: int = 2,
        poll_interval: float = 1.0,
        deregister_on_exit: bool = True
    ):
        self.server_url = server_url or _get_server_url()
        self.worker_id = worker_id or f"worker-{get_snowflake_id()}"
        self.max_workers = max_workers
        self.max_processes = max_processes
        self.poll_interval = poll_interval
        self._deregister_on_exit = deregister_on_exit

        # Initialize Jinja2 environment
        self._jinja = jinja2.Environment(
            loader=jinja2.BaseLoader(),
            undefined=jinja2.StrictUndefined
        )

        # Thread and process pools
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=f"worker-{self.worker_id}"
        )
        self._process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=self.max_processes
        )

        # Register this worker
        self._register_pool()

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info(f"Initialized worker {self.worker_id} with {self.max_workers} threads, {self.max_processes} processes")

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Worker {self.worker_id} received signal {signum}, shutting down...")
        if self._deregister_on_exit:
            _on_worker_terminate(self.worker_id, os.environ.get("NOETL_WORKER_POOL_NAME", "default"))
        os._exit(0)

    def _register_pool(self):
        """Register this worker in the runtime table."""
        pool_name = os.environ.get("NOETL_WORKER_POOL_NAME", "default")
        hostname = os.environ.get("HOSTNAME") or socket.gethostname()

        payload_runtime = {
            "type": "worker",
            "pid": os.getpid(),
            "hostname": hostname,
            "pool_name": pool_name,
            "max_workers": self.max_workers,
            "max_processes": self.max_processes,
        }

        runtime_json = json.dumps(payload_runtime)

        try:
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO runtime (runtime_id, name, component_type, base_url, status, labels, capacity, runtime, last_heartbeat, created_at, updated_at)
                        VALUES (%s, %s, 'worker', %s, 'ready', NULL, %s, %s, now(), now(), now())
                        ON CONFLICT (component_type, name)
                        DO UPDATE SET
                            base_url = EXCLUDED.base_url,
                            status = EXCLUDED.status,
                            capacity = EXCLUDED.capacity,
                            runtime = EXCLUDED.runtime,
                            last_heartbeat = now(),
                            updated_at = now()
                        """,
                        (get_snowflake_id(), self.worker_id, self.server_url, 1, runtime_json)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Failed to register worker {self.worker_id}: {e}")

    def _lease_job(self) -> Optional[Dict[str, Any]]:
        """Lease a job from the queue."""
        try:
            response = requests.post(
                f"{self.server_url}/jobs/lease",
                json={
                    "worker_id": self.worker_id,
                    "lease_duration_seconds": 300  # 5 minutes
                },
                timeout=10
            )

            if response.status_code == 200:
                job_data = response.json()
                logger.debug(f"Leased job {job_data.get('job_id')} for worker {self.worker_id}")
                return job_data
            elif response.status_code == 204:
                # No jobs available
                return None
            else:
                logger.error(f"Failed to lease job: {response.status_code} - {response.text}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while leasing job: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error while leasing job: {e}")
            return None

    def _complete_job(self, job_id: str, result: Any) -> bool:
        """Mark a job as completed."""
        try:
            response = requests.post(
                f"{self.server_url}/jobs/{job_id}/complete",
                json={
                    "worker_id": self.worker_id,
                    "result": result
                },
                timeout=30
            )

            if response.status_code == 200:
                logger.debug(f"Completed job {job_id}")
                return True
            else:
                logger.error(f"Failed to complete job {job_id}: {response.status_code} - {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while completing job {job_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while completing job {job_id}: {e}")
            return False

    def _fail_job(self, job_id: str, error: str) -> bool:
        """Mark a job as failed."""
        try:
            response = requests.post(
                f"{self.server_url}/jobs/{job_id}/fail",
                json={
                    "worker_id": self.worker_id,
                    "error": error
                },
                timeout=30
            )

            if response.status_code == 200:
                logger.debug(f"Failed job {job_id}: {error}")
                return True
            else:
                logger.error(f"Failed to mark job {job_id} as failed: {response.status_code} - {response.text}")
                return False

        except requests.exceptions.RequestException as e:
            logger.error(f"Request error while failing job {job_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while failing job {job_id}: {e}")
            return False

    def _execute_job_sync(self, job_data: Dict[str, Any]) -> tuple[bool, Any]:
        """Execute a job synchronously."""
        job_id = job_data.get('job_id')

        try:
            # Extract job parameters
            playbook_content = job_data.get('playbook_content')
            execution_id = job_data.get('execution_id')
            params = job_data.get('params', {})

            if not playbook_content:
                raise ValueError("No playbook content provided")

            if not execution_id:
                raise ValueError("No execution ID provided")

            logger.info(f"Executing job {job_id} with execution_id {execution_id}")

            # Execute the job using the job execution framework
            result = execute_job(
                playbook_content=playbook_content,
                execution_id=execution_id,
                params=params,
                worker_id=self.worker_id
            )

            logger.info(f"Job {job_id} completed successfully")
            return True, result

        except Exception as e:
            error_msg = f"Job {job_id} failed: {str(e)}"
            logger.error(error_msg)
            logger.exception("Job execution error details:")
            return False, error_msg

    async def _execute_job(self, job_data: Dict[str, Any]) -> None:
        """Execute a job asynchronously."""
        job_id = job_data.get('job_id')

        try:
            # Run the job in a thread pool to avoid blocking
            success, result = await asyncio.get_event_loop().run_in_executor(
                self._thread_pool,
                self._execute_job_sync,
                job_data
            )

            # Report result back to server
            if success:
                self._complete_job(job_id, result)
            else:
                self._fail_job(job_id, str(result))

        except Exception as e:
            error_msg = f"Async job execution failed: {str(e)}"
            logger.error(error_msg)
            self._fail_job(job_id, error_msg)

    async def run_forever(self):
        """Run the worker loop forever."""
        logger.info(f"Worker {self.worker_id} starting main loop")

        try:
            while True:
                try:
                    # Try to lease a job
                    job_data = self._lease_job()

                    if job_data:
                        # Execute the job asynchronously
                        asyncio.create_task(self._execute_job(job_data))
                    else:
                        # No jobs available, wait before polling again
                        await asyncio.sleep(self.poll_interval)

                except Exception as e:
                    logger.error(f"Error in worker main loop: {e}")
                    await asyncio.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info(f"Worker {self.worker_id} interrupted, shutting down...")
        except Exception as e:
            logger.error(f"Worker {self.worker_id} encountered fatal error: {e}")
        finally:
            if self._deregister_on_exit:
                _on_worker_terminate(self.worker_id, os.environ.get("NOETL_WORKER_POOL_NAME", "default"))

            # Cleanup resources
            self._thread_pool.shutdown(wait=True)
            self._process_pool.shutdown(wait=True)


class ScalableQueueWorkerPool:
    """A scalable pool of queue workers that can dynamically adjust the number of workers based on queue size."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        max_workers: int = 4,
        max_processes: int = 2,
        check_interval: float = 10.0,
        worker_poll_interval: float = 1.0,
    ):
        self.server_url = server_url or _get_server_url()
        self.max_workers = max_workers
        self.max_processes = max_processes
        self.check_interval = check_interval
        self.worker_poll_interval = worker_poll_interval

        # Thread and process pools for management
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="pool-manager"
        )
        self._process_pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=self.max_processes
        )

        # Worker management
        self._tasks: List[asyncio.Task] = []
        self._stop = False
        self._stopped = False

        logger.info(f"Initialized scalable worker pool with max {self.max_workers} workers")

    async def _queue_size(self) -> int:
        """Get the current queue size from the server."""
        try:
            response = requests.get(f"{self.server_url}/jobs/queue/size", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return data.get('size', 0)
            else:
                logger.error(f"Failed to get queue size: {response.status_code}")
                return 0
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error getting queue size: {e}")
            return 0
        except Exception as e:
            logger.error(f"Unexpected error getting queue size: {e}")
            return 0

    async def _spawn_worker(self) -> Optional[asyncio.Task]:
        """Spawn a new worker task."""
        try:
            worker = QueueWorker(
                server_url=self.server_url,
                max_workers=1,  # Each spawned worker handles one job at a time
                max_processes=1,
                poll_interval=self.worker_poll_interval,
                deregister_on_exit=False  # Pool manages registration
            )

            task = asyncio.create_task(worker.run_forever())
            logger.debug(f"Spawned new worker: {worker.worker_id}")
            return task

        except Exception as e:
            logger.error(f"Failed to spawn worker: {e}")
            return None

    async def _scale_workers(self):
        """Scale workers based on queue size."""
        queue_size = await self._queue_size()
        current_workers = len([t for t in self._tasks if not t.done()])

        # Simple scaling logic: one worker per job, up to max_workers
        target_workers = min(queue_size, self.max_workers)

        if target_workers > current_workers:
            # Scale up
            workers_to_add = target_workers - current_workers
            logger.info(f"Scaling up: adding {workers_to_add} workers (queue: {queue_size}, current: {current_workers})")

            for _ in range(workers_to_add):
                task = await self._spawn_worker()
                if task:
                    self._tasks.append(task)

        elif target_workers < current_workers and queue_size == 0:
            # Scale down only if queue is empty
            workers_to_remove = current_workers - target_workers
            logger.info(f"Scaling down: removing {workers_to_remove} workers (queue: {queue_size}, current: {current_workers})")

            # Cancel excess workers
            for _ in range(workers_to_remove):
                for task in self._tasks:
                    if not task.done():
                        task.cancel()
                        break

        # Clean up completed tasks
        self._tasks = [t for t in self._tasks if not t.done()]

    async def run_forever(self):
        """Run the scalable worker pool forever."""
        logger.info("Starting scalable worker pool")

        # Register the pool
        register_worker_pool_from_env()

        try:
            while not self._stop:
                await self._scale_workers()
                await asyncio.sleep(self.check_interval)

        except KeyboardInterrupt:
            logger.info("Worker pool interrupted, shutting down...")
        except Exception as e:
            logger.error(f"Worker pool encountered fatal error: {e}")
        finally:
            await self.stop()

    async def stop(self):
        """Stop the worker pool and all workers."""
        if self._stopped:
            return

        logger.info("Stopping worker pool...")
        self._stop = True

        # Cancel all worker tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Cleanup resources
        self._thread_pool.shutdown(wait=True)
        self._process_pool.shutdown(wait=True)

        # Deregister the pool
        try:
            deregister_worker_pool_from_env()
        except Exception as e:
            logger.error(f"Failed to deregister worker pool: {e}")

        self._stopped = True
        logger.info("Worker pool stopped")
