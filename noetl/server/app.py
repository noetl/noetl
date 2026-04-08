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
from noetl.core.urls import normalize_server_base_url
from noetl.server.api import router as api_router
from noetl.server.middleware import catch_exceptions_middleware

# Import V2 API
from noetl.server.api.v2 import (
    router as v2_router,
    ensure_batch_acceptor_started,
    shutdown_batch_acceptor,
    shutdown_publish_recovery_tasks,
    get_batch_metrics_snapshot,
)
from noetl.server.auto_resume import (
    resume_interrupted_executions,
    get_auto_resume_metrics_snapshot,
)
from noetl.server.runtime_leases import RuntimeLease, load_control_lease_seconds

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


def _create_app(settings: Settings) -> FastAPI:
    from contextlib import asynccontextmanager
    # Simple in-process metrics without external deps
    _process_start_time = time.time()
    _request_count_key = "noetl_request_total"
    _metrics_counters: Dict[str, int] = {_request_count_key: 0}

    def _logical_server_name() -> str:
        return settings.server_name or "server"

    def _server_instance_name() -> str:
        configured = os.getenv("NOETL_SERVER_INSTANCE_NAME", "").strip()
        if configured:
            return configured
        return f"{_logical_server_name()}@{settings.hostname}:{os.getpid()}"

    def register_server_directly(instance_name: str) -> None:
        from noetl.core.common import get_db_connection, get_snowflake_id
        server_url = settings.server_api_url
        labels = list(settings.server_labels or [])
        hostname = settings.hostname
        logical_name = _logical_server_name()
        labels.append(f"logical:{logical_name}")

        import datetime as _dt
        try:
            rid = get_snowflake_id()
        except Exception:
            rid = int(_dt.datetime.now().timestamp() * 1000)

        payload_runtime = {
            "type": "server",
            "logical_name": logical_name,
            "instance_name": instance_name,
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
                    (rid, instance_name, server_url, labels_json, runtime_json)
                )
                conn.commit()
        try:
            with open("/tmp/noetl_server_name", "w") as f:
                f.write(instance_name)
        except Exception:
            logger.debug("Could not write server instance name to /tmp/noetl_server_name", exc_info=True)

    def deregister_server_directly(instance_name: str) -> None:
        try:
            from noetl.core.common import get_db_connection
            with get_db_connection() as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        UPDATE runtime
                        SET status = 'offline', updated_at = now()
                        WHERE kind = 'server_api' AND name = %s
                        """,
                        (instance_name,)
                    )
                    conn.commit()
        except Exception as e:
            logger.error(f"Direct server deregistration failed: {e}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await init_pool(get_pgdb_connection())
        try:
            instance_name = _server_instance_name()
            logical_name = _logical_server_name()
            register_server_directly(instance_name)

            stop_event = asyncio.Event()
            sweep_interval = settings.runtime_sweep_interval
            offline_after = settings.runtime_offline_seconds
            auto_recreate_runtime = getattr(settings, 'auto_recreate_runtime', False)
            server_url = settings.server_api_url
            hostname = settings.hostname
            command_server_url = normalize_server_base_url(settings.server_url)
            control_lease_seconds = load_control_lease_seconds()

            runtime_sweeper_lease = RuntimeLease(
                task_name="runtime_sweeper",
                instance_name=instance_name,
                server_url=server_url,
                hostname=hostname,
                logical_name=logical_name,
                lease_seconds=control_lease_seconds,
            )
            auto_resume_lease = RuntimeLease(
                task_name="auto_resume",
                instance_name=instance_name,
                server_url=server_url,
                hostname=hostname,
                logical_name=logical_name,
                lease_seconds=control_lease_seconds,
            )
            async def _server_heartbeat_loop():
                while not stop_event.is_set():
                    try:
                        async with get_async_db_connection() as conn:
                            async with conn.cursor() as cur:
                                logger.debug(
                                    "About to update server heartbeat for %s",
                                    instance_name,
                                )
                                await cur.execute(
                                    """
                                    UPDATE runtime
                                    SET heartbeat = now(), updated_at = now(), status = 'ready'
                                    WHERE kind = 'server_api' AND name = %s
                                    """,
                                    (instance_name,),
                                )
                                if cur.rowcount == 0 and auto_recreate_runtime:
                                    logger.info(
                                        "Server runtime row missing for %s; auto recreating",
                                        instance_name,
                                    )
                                    import datetime as _dt

                                    try:
                                        rid = get_snowflake_id()
                                    except Exception:
                                        rid = int(_dt.datetime.now().timestamp() * 1000)

                                    runtime_payload = json.dumps(
                                        {
                                            "type": "server",
                                            "logical_name": logical_name,
                                            "instance_name": instance_name,
                                            "pid": os.getpid(),
                                            "hostname": hostname,
                                        }
                                    )
                                    await cur.execute(
                                        """
                                        INSERT INTO runtime (
                                            runtime_id, name, kind, uri, status, labels,
                                            capacity, runtime, heartbeat, created_at, updated_at
                                        )
                                        VALUES (
                                            %s, %s, 'server_api', %s, 'ready', NULL, NULL,
                                            %s::jsonb, now(), now(), now()
                                        )
                                        ON CONFLICT (kind, name)
                                        DO UPDATE SET
                                            uri = EXCLUDED.uri,
                                            status = EXCLUDED.status,
                                            runtime = EXCLUDED.runtime,
                                            heartbeat = now(),
                                            updated_at = now()
                                        """,
                                        (rid, instance_name, server_url, runtime_payload),
                                    )
                                await conn.commit()
                    except Exception as exc:
                        logger.exception(
                            "Server heartbeat refresh failed for %s: %s",
                            instance_name,
                            exc,
                        )
                    try:
                        await asyncio.sleep(sweep_interval)
                    except asyncio.CancelledError:
                        logger.info("Server heartbeat task cancelled; exiting")
                        break

            async def _runtime_sweeper():
                while not stop_event.is_set():
                    try:
                        lease_state = await runtime_sweeper_lease.try_acquire_or_renew()
                        if lease_state.acquired:
                            async with get_async_db_connection() as conn:
                                async with conn.cursor() as cur:
                                    await cur.execute(
                                        """
                                        UPDATE runtime
                                        SET status = 'offline', updated_at = now()
                                        WHERE status != 'offline'
                                          AND heartbeat < (now() - make_interval(secs => %s))
                                        """,
                                        (offline_after,),
                                    )
                                    await conn.commit()
                    except Exception as outer_e:
                        logger.exception(f"Runtime sweeper loop error: {outer_e}")
                    try:
                        await asyncio.sleep(sweep_interval)
                    except asyncio.CancelledError:
                        logger.info("Runtime sweeper task cancelled; exiting")
                        break

            async def _auto_resume_loop():
                completed = False
                retry_delay = min(5.0, max(1.0, float(sweep_interval)))
                while not stop_event.is_set() and not completed:
                    try:
                        lease_state = await auto_resume_lease.try_acquire_or_renew()
                        if lease_state.acquired:
                            await resume_interrupted_executions()
                            completed = True
                            await auto_resume_lease.release()
                            break
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.error(
                            "Auto-resume startup failed (non-fatal): %s",
                            exc,
                            exc_info=True,
                        )
                    try:
                        await asyncio.sleep(retry_delay)
                    except asyncio.CancelledError:
                        logger.info("Auto-resume task cancelled; exiting")
                        break

            # Start async batch acceptance workers (202 + request_id contract).
            try:
                await ensure_batch_acceptor_started()
            except Exception as e:
                logger.error(f"Batch acceptor startup failed (non-fatal): {e}", exc_info=True)

            heartbeat_task: Optional[asyncio.Task] = None
            sweeper_task: Optional[asyncio.Task] = None
            auto_resume_task: Optional[asyncio.Task] = None
            try:
                logger.info("Starting server heartbeat background task...")
                heartbeat_task = asyncio.create_task(_server_heartbeat_loop(), name="server-heartbeat")
                logger.info("Server heartbeat background task started successfully")
            except Exception as e:
                logger.exception(f"Failed to start server heartbeat: {e}")

            try:
                logger.info("Starting runtime sweeper background task...")
                sweeper_task = asyncio.create_task(_runtime_sweeper())
                logger.info("Runtime sweeper background task started successfully")
            except Exception as e:
                logger.exception(f"Failed to start task: {e}")

            try:
                logger.info("Starting auto-resume coordination task...")
                auto_resume_task = asyncio.create_task(
                    _auto_resume_loop(),
                    name="auto-resume-recovery",
                )
                logger.info("Auto-resume coordination task started successfully")
            except Exception as e:
                logger.error(f"Auto-resume startup failed (non-fatal): {e}", exc_info=True)

            yield
            # Shutdown
            stop_event.set()
            if heartbeat_task:
                try:
                    heartbeat_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await heartbeat_task
                except Exception as e:
                    logger.exception(f"Critical error during heartbeat task shutdown: {e}")
            if sweeper_task:
                try:
                    sweeper_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await sweeper_task
                except Exception as e:
                    logger.exception(f"Critical error during sweeper task shutdown: {e}")
            if auto_resume_task:
                try:
                    auto_resume_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await auto_resume_task
                except Exception as e:
                    logger.exception(f"Critical error during auto-resume task shutdown: {e}")
            try:
                await shutdown_publish_recovery_tasks()
            except Exception as e:
                logger.error(f"Publish recovery task shutdown failed: {e}", exc_info=True)
            try:
                await shutdown_batch_acceptor()
            except Exception as e:
                logger.error(f"Batch acceptor shutdown failed: {e}", exc_info=True)
            try:
                await runtime_sweeper_lease.release()
                await auto_resume_lease.release()
                deregister_server_directly(instance_name)
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

        # Async batch acceptance metrics
        batch_metrics = get_batch_metrics_snapshot()
        lines.append("# HELP noetl_batch_accepted_total Total accepted /api/events/batch requests")
        lines.append("# TYPE noetl_batch_accepted_total counter")
        lines.append(f"noetl_batch_accepted_total {batch_metrics.get('accepted_total', 0.0)}")
        lines.append("# HELP noetl_batch_enqueue_error_total Total enqueue errors on /api/events/batch")
        lines.append("# TYPE noetl_batch_enqueue_error_total counter")
        lines.append(f"noetl_batch_enqueue_error_total {batch_metrics.get('enqueue_error_total', 0.0)}")
        lines.append("# HELP noetl_batch_ack_timeout_total Total enqueue ack timeouts on /api/events/batch")
        lines.append("# TYPE noetl_batch_ack_timeout_total counter")
        lines.append(f"noetl_batch_ack_timeout_total {batch_metrics.get('ack_timeout_total', 0.0)}")
        lines.append("# HELP noetl_batch_queue_unavailable_total Total queue unavailable errors")
        lines.append("# TYPE noetl_batch_queue_unavailable_total counter")
        lines.append(f"noetl_batch_queue_unavailable_total {batch_metrics.get('queue_unavailable_total', 0.0)}")
        lines.append("# HELP noetl_batch_worker_unavailable_total Total worker unavailable errors")
        lines.append("# TYPE noetl_batch_worker_unavailable_total counter")
        lines.append(f"noetl_batch_worker_unavailable_total {batch_metrics.get('worker_unavailable_total', 0.0)}")
        lines.append("# HELP noetl_batch_processing_timeout_total Total async batch processing timeouts")
        lines.append("# TYPE noetl_batch_processing_timeout_total counter")
        lines.append(f"noetl_batch_processing_timeout_total {batch_metrics.get('processing_timeout_total', 0.0)}")
        lines.append("# HELP noetl_batch_queue_depth Current in-memory async batch queue depth")
        lines.append("# TYPE noetl_batch_queue_depth gauge")
        lines.append(f"noetl_batch_queue_depth {batch_metrics.get('queue_depth', 0.0)}")
        lines.append("# HELP noetl_batch_enqueue_latency_seconds Batch enqueue latency summary (sum/count)")
        lines.append("# TYPE noetl_batch_enqueue_latency_seconds summary")
        lines.append(
            f"noetl_batch_enqueue_latency_seconds_sum {batch_metrics.get('enqueue_latency_seconds_sum', 0.0)}"
        )
        lines.append(
            f"noetl_batch_enqueue_latency_seconds_count {batch_metrics.get('enqueue_latency_seconds_count', 0.0)}"
        )
        lines.append("# HELP noetl_batch_first_worker_claim_latency_seconds Delay from acceptance to first worker claim")
        lines.append("# TYPE noetl_batch_first_worker_claim_latency_seconds summary")
        lines.append(
            "noetl_batch_first_worker_claim_latency_seconds_sum "
            f"{batch_metrics.get('first_worker_claim_latency_seconds_sum', 0.0)}"
        )
        lines.append(
            "noetl_batch_first_worker_claim_latency_seconds_count "
            f"{batch_metrics.get('first_worker_claim_latency_seconds_count', 0.0)}"
        )

        auto_resume_metrics = get_auto_resume_metrics_snapshot()
        lines.append("# HELP noetl_auto_resume_attempts_total Dependency readiness attempts for auto-recovery")
        lines.append("# TYPE noetl_auto_resume_attempts_total counter")
        lines.append(f"noetl_auto_resume_attempts_total {auto_resume_metrics.get('attempts_total', 0.0)}")
        lines.append("# HELP noetl_auto_resume_dependency_not_ready_total Auto-recovery readiness check failures")
        lines.append("# TYPE noetl_auto_resume_dependency_not_ready_total counter")
        lines.append(
            "noetl_auto_resume_dependency_not_ready_total "
            f"{auto_resume_metrics.get('dependency_not_ready_total', 0.0)}"
        )
        lines.append("# HELP noetl_auto_resume_recoveries_started_total Auto-recovery runs started")
        lines.append("# TYPE noetl_auto_resume_recoveries_started_total counter")
        lines.append(
            "noetl_auto_resume_recoveries_started_total "
            f"{auto_resume_metrics.get('recoveries_started_total', 0.0)}"
        )
        lines.append("# HELP noetl_auto_resume_recoveries_completed_total Auto-recovery runs completed")
        lines.append("# TYPE noetl_auto_resume_recoveries_completed_total counter")
        lines.append(
            "noetl_auto_resume_recoveries_completed_total "
            f"{auto_resume_metrics.get('recoveries_completed_total', 0.0)}"
        )
        lines.append("# HELP noetl_auto_resume_recoveries_failed_total Auto-recovery failures")
        lines.append("# TYPE noetl_auto_resume_recoveries_failed_total counter")
        lines.append(
            "noetl_auto_resume_recoveries_failed_total "
            f"{auto_resume_metrics.get('recoveries_failed_total', 0.0)}"
        )
        lines.append("# HELP noetl_auto_resume_recoveries_restarted_total Interrupted executions restarted by auto-recovery")
        lines.append("# TYPE noetl_auto_resume_recoveries_restarted_total counter")
        lines.append(
            "noetl_auto_resume_recoveries_restarted_total "
            f"{auto_resume_metrics.get('recoveries_restarted_total', 0.0)}"
        )

        body = "\n".join(lines) + "\n"
        return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


    @app.get("/", include_in_schema=False)
    async def root():
        return {"message": "NoETL API is running (Standalone GUI available externally)"}

    return app
