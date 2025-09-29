import os
import json
import yaml
import tempfile
import os
import json
import yaml
import tempfile
import contextlib
import psycopg
import base64
import socket
import time
import datetime
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, List
import asyncio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from noetl.core.common import deep_merge, get_pgdb_connection, get_db_connection, get_async_db_connection, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.api.routers.broker import Broker, execute_playbook_via_broker
from noetl.api.routers import router as api_router
logger = setup_logger(__name__, include_location=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from noetl.core.config import get_settings
import time

router = APIRouter()
router.include_router(api_router)


def create_app() -> FastAPI:
    from noetl.core.config import _settings
    import noetl.core.config as core_config
    core_config._settings = None
    core_config._ENV_LOADED = False

    settings = get_settings(reload=True)

    import logging
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.INFO
    )

    return _create_app(settings.enable_ui)


def _create_app(enable_ui: bool = True) -> FastAPI:
    from contextlib import asynccontextmanager

    # Simple in-process metrics without external deps
    _process_start_time = time.time()
    _request_count_key = "noetl_request_total"
    _metrics_counters: Dict[str, int] = { _request_count_key: 0 }

    def register_server_directly() -> None:
        from noetl.core.common import get_db_connection, get_snowflake_id
        import socket as _socket

        settings = get_settings()
        server_url = (getattr(settings, 'server_url', '') or '').strip()
        if not server_url:
            raise RuntimeError("settings.server_url is required but not set")
        if not server_url.endswith('/api'):
            server_url = server_url + '/api'

        name = (getattr(settings, 'server_name', '') or '').strip()
        if not name:
            raise RuntimeError("settings.server_name is required but not set")

        labels_env = os.environ.get("NOETL_SERVER_LABELS")
        if labels_env:
            labels = [s.strip() for s in labels_env.split(',') if s.strip()]
        else:
            labels = None

        hostname = os.environ.get("HOSTNAME") or _socket.gethostname()

        import datetime as _dt
        try:
            rid = get_snowflake_id()
        except Exception:
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
                    f"""
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

    def deregister_server_directly() -> None:
        try:
            from noetl.core.common import get_db_connection
            name: Optional[str] = None
            if os.path.exists('/tmp/noetl_server_name'):
                try:
                    with open('/tmp/noetl_server_name', 'r') as f:
                        name = f.read().strip()
                except Exception:
                    name = None
            if not name:
                try:
                    name = get_settings().server_name
                except Exception:
                    name = os.environ.get('NOETL_SERVER_NAME')
            if not name:
                return
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
        except Exception as e:
            logger.error(f"Direct server deregistration failed: {e}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        register_server_directly()

        # --------------------------------------------------
        # Background runtime sweeper / server heartbeat
        # --------------------------------------------------
        stop_event = asyncio.Event()
        sweep_interval = float(os.environ.get("NOETL_RUNTIME_SWEEP_INTERVAL", "15"))
        offline_after = int(os.environ.get("NOETL_RUNTIME_OFFLINE_SECONDS", "60"))
        try:
            server_settings = get_settings()
            server_name = server_settings.server_name
            auto_recreate_runtime = getattr(server_settings, 'auto_recreate_runtime', False)
            server_url = server_settings.server_url.rstrip('/')
        except Exception:
            server_name = os.environ.get("NOETL_SERVER_NAME", "server-local")
            auto_recreate_runtime = False
            server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8082").rstrip('/')
        if not server_url.endswith('/api'):
            server_url = server_url + '/api'
        hostname = os.environ.get("HOSTNAME") or socket.gethostname()

        async def _report_server_metrics(component_name: str):
            """Report server metrics periodically."""
            try:
                import httpx
                from ..api.routers.metrics import collect_system_metrics
                
                # Collect system metrics
                metrics_data = collect_system_metrics()
                
                # Add server-specific metrics
                try:
                    # Number of connected workers
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                """
                                SELECT COUNT(*) FROM runtime 
                                WHERE component_type IN ('worker_pool', 'queue_worker') 
                                AND status = 'ready'
                                """
                            )
                            row = await cur.fetchone()
                            worker_count = row[0] if row else 0
                            
                            await cur.execute(
                                """
                                SELECT COUNT(*) FROM queue 
                                WHERE status = 'pending'
                                """
                            )
                            row = await cur.fetchone()
                            queue_size = row[0] if row else 0
                    
                    metrics_data.extend([
                        {
                            "metric_name": "noetl_server_active_workers",
                            "metric_type": "gauge",
                            "metric_value": worker_count,
                            "help_text": "Number of active workers",
                            "unit": "workers"
                        },
                        {
                            "metric_name": "noetl_server_queue_size", 
                            "metric_type": "gauge",
                            "metric_value": queue_size,
                            "help_text": "Current queue size",
                            "unit": "jobs"
                        }
                    ])
                except Exception as e:
                    logger.debug(f"Failed to collect server-specific metrics: {e}")
                
                # Report via self-report endpoint
                payload = {
                    "component_name": component_name,
                    "component_type": "server_api",
                    "metrics": [
                        {
                            "metric_name": m.metric_name if hasattr(m, 'metric_name') else m.get("metric_name", ""),
                            "metric_type": m.metric_type if hasattr(m, 'metric_type') else m.get("metric_type", "gauge"),
                            "metric_value": m.metric_value if hasattr(m, 'metric_value') else m.get("metric_value", 0),
                            "timestamp": datetime.datetime.now().isoformat(),
                            "labels": {
                                "component": component_name,
                                "hostname": hostname,
                                "instance": component_name
                            },
                            "help_text": m.help_text if hasattr(m, 'help_text') else m.get("help_text", ""),
                            "unit": m.unit if hasattr(m, 'unit') else m.get("unit", "")
                        } for m in metrics_data
                    ]
                }
                
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(f"{server_url}/metrics/report", json=payload)
                    if resp.status_code != 200:
                        logger.debug(f"Server metrics report failed {resp.status_code}: {resp.text}")
                        
            except Exception as e:
                logger.debug(f"Failed to report server metrics: {e}")

        async def _runtime_sweeper():
            last_metrics_time = 0.0
            metrics_interval = float(os.environ.get("NOETL_SERVER_METRICS_INTERVAL", "60"))
            
            while not stop_event.is_set():
                try:
                    current_time = time.time()
                    
                    async with get_async_db_connection() as conn:
                        async with conn.cursor() as cur:
                            # Mark stale (non-offline) runtimes offline
                            try:
                                await cur.execute(
                                    """
                                    UPDATE runtime SET status = 'offline', updated_at = now()
                                    WHERE status != 'offline' AND last_heartbeat < (now() - interval '%s seconds')
                                    """,
                                    (offline_after,)
                                )
                            except Exception as e:
                                logger.debug(f"Runtime offline sweep failed: {e}")

                            # Server heartbeat
                            try:
                                await cur.execute(
                                    """
                                    UPDATE runtime 
                                    SET last_heartbeat = now(), updated_at = now(), status = 'ready'
                                    WHERE component_type = 'server_api' AND name = %s
                                    """,
                                    (server_name,)
                                )
                                if cur.rowcount == 0 and auto_recreate_runtime:
                                    logger.info("Server runtime row missing; auto recreating")
                                    import datetime as _dt
                                    try:
                                        rid = get_snowflake_id()
                                    except Exception:
                                        rid = int(_dt.datetime.now().timestamp() * 1000)

                                    runtime_payload = json.dumps({
                                        "type": "server",
                                        "pid": os.getpid(),
                                        "hostname": hostname,
                                    })

                                    await cur.execute(
                                        """
                                        INSERT INTO runtime (runtime_id, name, component_type, base_url, status, labels, capacity, runtime, last_heartbeat, created_at, updated_at)
                                        VALUES (%s, %s, 'server_api', %s, 'ready', NULL, NULL, %s::jsonb, now(), now(), now())
                                        ON CONFLICT (component_type, name)
                                        DO UPDATE SET
                                            base_url = EXCLUDED.base_url,
                                            status = EXCLUDED.status,
                                            runtime = EXCLUDED.runtime,
                                            last_heartbeat = now(),
                                            updated_at = now()
                                        """,
                                        (rid, server_name, server_url, runtime_payload)
                                    )
                            except Exception as e:
                                logger.debug(f"Server heartbeat refresh failed: {e}")
                            try:
                                await conn.commit()
                            except Exception:
                                pass
                    
                    # Report server metrics periodically
                    if current_time - last_metrics_time >= metrics_interval:
                        try:
                            await _report_server_metrics(server_name)
                            last_metrics_time = current_time
                        except Exception as e:
                            logger.debug(f"Server metrics reporting failed: {e}")
                            
                except Exception as outer_e:
                    logger.debug(f"Runtime sweeper loop error: {outer_e}")
                await asyncio.sleep(sweep_interval)

        sweeper_task: Optional[asyncio.Task] = None
        try:
            sweeper_task = asyncio.create_task(_runtime_sweeper())
        except Exception as e:
            logger.debug(f"Failed to start runtime sweeper: {e}")

        yield
        # Shutdown
        stop_event.set()
        if sweeper_task:
            try:
                sweeper_task.cancel()
                with contextlib.suppress(Exception):
                    await sweeper_task
            except Exception:
                pass
        try:
            deregister_server_directly()
        except Exception as e:
            logger.debug(f"Server deregistration failed during shutdown: {e}")

    settings = get_settings()

    app = FastAPI(
        title="NoETL API",
        description="NoETL API server",
        version=settings.app_version,
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Simple request counter middleware (exclude /metrics to avoid recursion)
    @app.middleware("http")
    async def _count_requests(request, call_next):
        if not request.url.path.startswith("/metrics"):
            try:
                _metrics_counters[_request_count_key] = _metrics_counters.get(_request_count_key, 0) + 1
            except Exception:
                pass
        response = await call_next(request)
        return response

    ui_build_path = settings.ui_build_path

    app.include_router(router, prefix="/api")

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    @app.get("/metrics", include_in_schema=False)
    async def metrics():
        # Build a minimal Prometheus exposition
        # HELP/TYPE lines are optional but helpful
        lines = []
        lines.append("# HELP noetl_up NoETL server up status")
        lines.append("# TYPE noetl_up gauge")
        lines.append("noetl_up 1")

        # Build info
        try:
            name = settings.server_name
        except Exception:
            name = "unknown"
        ver = settings.app_version
        lines.append("# HELP noetl_info Build and server info")
        lines.append("# TYPE noetl_info gauge")
        # Escape backslashes and quotes in labels if any
        def _esc(s: str) -> str:
            return str(s).replace("\\", "\\\\").replace("\"", "\\\"")
        lines.append(f"noetl_info{{version=\"{_esc(ver)}\",name=\"{_esc(name)}\"}} 1")

        # Process start time
        lines.append("# HELP noetl_process_start_time_seconds Start time of the NoETL process since unix epoch in seconds")
        lines.append("# TYPE noetl_process_start_time_seconds gauge")
        lines.append(f"noetl_process_start_time_seconds {_process_start_time}")

        # Request counter
        lines.append("# HELP noetl_request_total Total HTTP requests served")
        lines.append("# TYPE noetl_request_total counter")
        lines.append(f"noetl_request_total {_metrics_counters.get(_request_count_key, 0)}")

        body = "\n".join(lines) + "\n"
        return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")

    if enable_ui and ui_build_path.exists():
        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            favicon_file = settings.favicon_file
            if favicon_file.exists():
                return FileResponse(favicon_file)
            return FileResponse(ui_build_path / "index.html")

        app.mount("/assets", StaticFiles(directory=ui_build_path / "assets"), name="assets")

        @app.get("/{catchall:path}", include_in_schema=False)
        async def spa_catchall(catchall: str):
            # Don't serve UI for API paths
            if catchall.startswith("api/"):
                from fastapi import HTTPException
                raise HTTPException(status_code=404, detail="API endpoint not found")
            return FileResponse(ui_build_path / "index.html")

        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(ui_build_path / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def root_no_ui():
            return {"message": "NoETL API is running, but UI is not available"}

    return app
