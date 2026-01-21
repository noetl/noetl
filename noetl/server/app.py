from noetl.core.config import get_settings, Settings
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI
import os
import json
import contextlib
import time
from typing import Dict, Optional
import asyncio
from fastapi import APIRouter
from noetl.core.common import get_async_db_connection, get_pgdb_connection, get_snowflake_id
from noetl.core.db.pool import init_pool, close_pool
from noetl.core.logger import setup_logger
from noetl.server.api import router as api_router
from noetl.server.middleware import catch_exceptions_middleware

# Import V2 API
from noetl.server.api.v2 import router as v2_router

logger = setup_logger(__name__, include_location=True)


router = APIRouter()
# v2 (event-driven) routes are the primary API; legacy routes are still included
# for non-execution resources.
router.include_router(v2_router)
router.include_router(api_router)


def create_app() -> FastAPI:
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

    return _create_app(settings=settings)


def _create_app(settings: Settings, enable_ui: Optional[bool] = None) -> FastAPI:
    from contextlib import asynccontextmanager
    if enable_ui is None:
        enable_ui = settings.enable_ui

    # Simple in-process metrics without external deps
    _process_start_time = time.time()
    _request_count_key = "noetl_request_total"
    _metrics_counters: Dict[str, int] = {_request_count_key: 0}

    def register_server_directly() -> None:
        from noetl.core.common import get_db_connection, get_snowflake_id
        server_url = settings.server_api_url
        name = settings.server_name
        labels = settings.server_labels or None
        hostname = settings.hostname

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
                    INSERT INTO runtime (runtime_id, name, kind, uri, status, labels, capacity, runtime, heartbeat, created_at, updated_at)
                    VALUES (%s, %s, 'server_api', %s, 'ready', %s, NULL, %s, now(), now(), now())
                    ON CONFLICT (kind, name)
                    DO UPDATE SET
                        uri = EXCLUDED.uri,
                        status = EXCLUDED.status,
                        labels = EXCLUDED.labels,
                        runtime = EXCLUDED.runtime,
                        heartbeat = now(),
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
                name = settings.server_name
            if not name:
                return
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE runtime
                        SET status = 'offline', updated_at = now()
                        WHERE kind = 'server_api' AND name = %s
                        """,
                        (name,)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Direct server deregistration failed: {e}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_pool(get_pgdb_connection())
        try:
            register_server_directly()

            # --------------------------------------------------
            # Background runtime sweeper / server heartbeat
            # --------------------------------------------------
            stop_event = asyncio.Event()
            sweep_interval = settings.runtime_sweep_interval
            offline_after = settings.runtime_offline_seconds
            server_name = settings.server_name
            auto_recreate_runtime = getattr(settings, 'auto_recreate_runtime', False)
            server_url = settings.server_api_url
            hostname = settings.hostname

            async def _runtime_sweeper():
                while not stop_event.is_set():
                    try:
                        async with get_async_db_connection() as conn:
                            async with conn.cursor() as cur:
                                # Mark stale (non-offline) runtimes offline
                                try:
                                    await cur.execute(
                                        """
                                        UPDATE runtime SET status = 'offline', updated_at = now()
                                        WHERE status != 'offline' AND heartbeat < (now() - make_interval(secs => %s))
                                        """,
                                        (offline_after,)
                                    )
                                except Exception as e:
                                    logger.exception(f"Runtime offline sweep failed: {e}")

                                # Server heartbeat
                                try:
                                    logger.debug(f"About to update server heartbeat for {server_name}")
                                    await cur.execute(
                                        """
                                        UPDATE runtime 
                                        SET heartbeat = now(), updated_at = now(), status = 'ready'
                                        WHERE kind = 'server_api' AND name = %s
                                        """,
                                        (server_name,)
                                    )
                                    logger.debug(f"Server heartbeat updated for {server_name}, rows affected: {cur.rowcount}")
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
                                            INSERT INTO runtime (runtime_id, name, kind, uri, status, labels, capacity, runtime, heartbeat, created_at, updated_at)
                                            VALUES (%s, %s, 'server_api', %s, 'ready', NULL, NULL, %s::jsonb, now(), now(), now())
                                            ON CONFLICT (kind, name)
                                            DO UPDATE SET
                                                uri = EXCLUDED.uri,
                                                status = EXCLUDED.status,
                                                runtime = EXCLUDED.runtime,
                                                heartbeat = now(),
                                                updated_at = now()
                                            """,
                                            (rid, server_name, server_url, runtime_payload)
                                        )
                                except Exception as e:
                                    logger.exception(f"Server heartbeat refresh failed: {e}")
                                try:
                                    await conn.commit()
                                    logger.debug(f"Runtime sweeper transaction committed successfully")
                                except Exception as e:
                                    logger.exception(f"Runtime sweeper commit failed: {e}")

                        # Note: V2 uses NATS for command distribution, no queue table to reclaim

                    except Exception as outer_e:
                        logger.exception(f"Runtime sweeper loop error: {outer_e}")
                    try:
                        await asyncio.sleep(sweep_interval)
                    except asyncio.CancelledError:
                        logger.info("Runtime sweeper task cancelled; exiting")
                        break

            sweeper_task: Optional[asyncio.Task] = None
            try:
                logger.info("Starting runtime sweeper background task...")
                sweeper_task = asyncio.create_task(_runtime_sweeper())
                logger.info("Runtime sweeper background task started successfully")
            except Exception as e:
                logger.exception(f"Failed to start runtime sweeper: {e}")

            yield
            # Shutdown
            stop_event.set()
            if sweeper_task:
                try:
                    sweeper_task.cancel()
                    with contextlib.suppress(Exception):
                        await sweeper_task
                except Exception as e:
                    logger.exception(f"Critical error during sweeper task shutdown: {e}")
            try:
                deregister_server_directly()
            except Exception as e:
                logger.error(f"Server deregistration failed during shutdown: {e}")
                # Don't pass this silently - log but continue shutdown
        finally:
            await close_pool()

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

    app.middleware('http')(catch_exceptions_middleware)

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
            return FileResponse(
                ui_build_path / "index.html",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )

        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(
                ui_build_path / "index.html",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
    else:
        @app.get("/", include_in_schema=False)
        async def root_no_ui():
            logger.error(f"ERROR: UI not available you need to build it first (see docs) and put dist to {ui_build_path}")
            return {"message": "NoETL API is running, but UI is not available"}

    return app
