from __future__ import annotations

import os
import sys
import time
from typing import Optional

import httpx

from noetl.core.config import (
    Settings,
    WorkerSettings,
    get_settings,
    get_worker_settings,
)
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def resolve_server_settings(settings: Optional[Settings] = None) -> Settings:
    return settings or get_settings()


def resolve_worker_settings(
    settings: Optional[WorkerSettings] = None,
) -> WorkerSettings:
    return settings or get_worker_settings()


_resolve_server_settings = resolve_server_settings
_resolve_worker_settings = resolve_worker_settings


def register_server_from_env(settings: Optional[Settings] = None) -> None:
    """Register this server instance with the server registry."""
    try:
        settings = resolve_server_settings(settings)

        payload = {
            "name": settings.server_name or f"server-{settings.hostname}",
            "component_type": "server_api",
            "runtime": "server",
            "base_url": settings.server_api_url,
            "status": "ready",
            "capacity": None,
            "labels": settings.server_labels or None,
            "pid": os.getpid(),
            "hostname": settings.hostname,
        }
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(settings.endpoint_runtime_register, json=payload)
            if resp.status_code == 200:
                logger.info(
                    "Server registered: %s -> %s",
                    payload["name"],
                    settings.server_api_url,
                )
                try:
                    with open("/tmp/noetl_server_name", "w") as f:
                        f.write(payload["name"])
                except (IOError, OSError, PermissionError) as exc:
                    logger.warning(
                        "Could not write server name to /tmp/noetl_server_name: %s",
                        exc,
                    )
            else:
                logger.warning(
                    "Server register failed (%s): %s", resp.status_code, resp.text
                )
    except Exception as exc:
        logger.exception(f"Unexpected error during server registration: {exc}")


def deregister_server_from_env(settings: Optional[Settings] = None) -> None:
    """Deregister server using stored name via HTTP (no DB fallback)."""
    try:
        settings = resolve_server_settings(settings)
        name: Optional[str] = None
        if os.path.exists("/tmp/noetl_server_name"):
            try:
                with open("/tmp/noetl_server_name", "r") as f:
                    name = f.read().strip()
            except Exception:
                name = None
        if not name:
            name = settings.server_name
        if not name:
            return

        try:
            resp = httpx.request(
                "DELETE",
                settings.endpoint_runtime_deregister,
                json={"name": name, "component_type": "server_api"},
                timeout=5.0,
            )
            logger.info(
                "Server deregister response: %s - %s", resp.status_code, resp.text
            )
        except Exception as exc:
            logger.exception(f"Server deregister HTTP error: {exc}")

        try:
            os.remove("/tmp/noetl_server_name")
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.exception(f"Failed to remove server name file: {exc}")
        logger.info("Deregistered server: %s", name)
    except Exception as exc:
        logger.exception(f"Server deregistration exception details: {exc}")


def register_worker_pool_from_env(
    worker_settings: Optional[WorkerSettings] = None,
) -> None:
    """Register this worker pool with the server registry using worker settings."""
    try:
        worker_settings = resolve_worker_settings(worker_settings)

        if worker_settings.namespace:
            worker_uri = f"k8s://{worker_settings.namespace}/{worker_settings.hostname}"
        else:
            worker_uri = f"local://{worker_settings.hostname}"

        payload = {
            "name": worker_settings.resolved_pool_name,
            "runtime": worker_settings.pool_runtime,
            "uri": worker_uri,
            "status": "ready",
            "capacity": worker_settings.worker_capacity,
            "labels": worker_settings.worker_labels or None,
            "pid": os.getpid(),
            "hostname": worker_settings.hostname,
        }

        logger.info(
            "Registering worker pool '%s' with runtime '%s' at %s",
            worker_settings.resolved_pool_name,
            worker_settings.pool_runtime,
            worker_settings.endpoint_worker_pool_register,
        )

        with httpx.Client(timeout=10.0) as client:
            resp = client.post(
                worker_settings.endpoint_worker_pool_register, json=payload
            )
            if resp.status_code == 200:
                logger.info(
                    "Worker pool registered: %s (%s) -> %s",
                    payload["name"],
                    payload["runtime"],
                    payload["uri"],
                )
                with open(f"/tmp/noetl_worker_pool_name_{payload['name']}", "w") as f:
                    f.write(payload["name"])
            else:
                logger.warning(
                    "Worker pool register failed (%s): %s",
                    resp.status_code,
                    resp.text,
                )
                raise RuntimeError(
                    f"Registration failed with status {resp.status_code}: {resp.text}"
                )

    except Exception as exc:
        logger.exception(f"Unexpected error during worker pool registration: {exc}")
        raise


def deregister_worker_pool_from_env(
    worker_settings: Optional[WorkerSettings] = None,
) -> None:
    """Attempt to deregister worker pool using stored name (HTTP only)."""
    logger.info("Worker deregistration starting...")
    try:
        worker_settings = resolve_worker_settings(worker_settings)
        name: Optional[str] = (worker_settings.pool_name or "").strip()

        if name:
            logger.info("Using worker name from config: %s", name)
            worker_file = f"/tmp/noetl_worker_pool_name_{name}"
            if os.path.exists(worker_file):
                with open(worker_file, "r") as f:
                    name = f.read().strip()
                logger.info("Found worker name from file: %s", name)

        if not name:
            logger.warning("No worker name found for deregistration")
            return

        logger.info(
            "Attempting to deregister worker %s via %s",
            name,
            worker_settings.endpoint_worker_pool_deregister,
        )

        resp = httpx.request(
            "DELETE",
            worker_settings.endpoint_worker_pool_deregister,
            json={"name": name},
            timeout=5.0,
        )
        logger.info("Worker deregister response: %s - %s", resp.status_code, resp.text)

        worker_file = f"/tmp/noetl_worker_pool_name_{name}"
        if os.path.exists(worker_file):
            os.remove(worker_file)
            logger.info("Removed worker-specific name file")
        elif os.path.exists("/tmp/noetl_worker_pool_name"):
            os.remove("/tmp/noetl_worker_pool_name")
            logger.info(f"Deregistered worker pool: {name} | removed_legacy_file=true")
        else:
            logger.info(f"Deregistered worker pool: {name}")
    except Exception as exc:
        logger.exception(f"Worker deregister general error: {exc}")


def on_worker_terminate(signum):
    logger.info("Worker pool process received signal %s", signum)
    try:
        worker_settings = resolve_worker_settings()
        retries = worker_settings.deregister_retries
        backoff_base = worker_settings.deregister_backoff
        for attempt in range(1, retries + 1):
            try:
                logger.info("Worker deregister attempt %s", attempt)
                deregister_worker_pool_from_env(worker_settings)
                logger.info("Worker: deregister succeeded (attempt %s)", attempt)
                break
            except Exception as exc:
                logger.exception(f"Worker: deregister attempt {attempt} failed: {exc}")
            if attempt < retries:
                time.sleep(backoff_base * (2 ** (attempt - 1)))
    finally:
        logger.info("Worker termination signal handler completed")
        sys.exit(1)
