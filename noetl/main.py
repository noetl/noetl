from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from noetl.server import router as server_router
from noetl.system import router as system_router
from noetl.worker import router as worker_router, register_worker_pool_from_env
from noetl.logger import setup_logger
import uvicorn


logger = setup_logger(__name__, include_location=True)

def _validate_required_env():
    required_vars = [
        "NOETL_USER",
        "NOETL_PASSWORD",
        "NOETL_SCHEMA",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "NOETL_ENCRYPTION_KEY",
    ]
    missing = [v for v in required_vars if not os.environ.get(v)]
    if missing:
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        raise SystemExit(1)

_enable_ui = True

def create_app() -> FastAPI:
    global _enable_ui


    _validate_required_env()

    # Configure base logging to stdout
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.INFO
    )

    # Also log to file so that logs populate even if process wasn't started via our wrapper scripts
    try:
        project_root = Path(__file__).resolve().parents[1]
        logs_dir = project_root / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        component = "worker" if os.environ.get("NOETL_ENABLE_WORKER_API", "false").lower() in ("1","true","yes","y","on") else "server"
        log_file = logs_dir / f"{component}.log"
        # Avoid adding duplicate handlers (e.g., on reload)
        root_logger = logging.getLogger()
        existing = False
        for h in root_logger.handlers:
            try:
                if isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', None) == str(log_file):
                    existing = True
                    break
            except Exception:
                continue
        if not existing:
            fh = logging.FileHandler(str(log_file))
            fmt = logging.Formatter('[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s', '%Y-%m-%dT%H:%M:%S')
            fh.setFormatter(fmt)
            fh.setLevel(logging.INFO)
            root_logger.addHandler(fh)
            # Attach to uvicorn loggers as well
            for lname in ("uvicorn", "uvicorn.error", "uvicorn.access"):
                try:
                    lg = logging.getLogger(lname)
                    lg.addHandler(fh)
                except Exception:
                    pass
    except Exception as log_e:
        logger.debug(f"File logging setup skipped/failed: {log_e}")

    # Log environment snapshot via logger (in addition to stdout prints)
    try:
        logger.info("=== ENVIRONMENT VARIABLES AT SERVER STARTUP ===")
        for key, value in sorted(os.environ.items()):
            logger.info("ENV: %s=%s", key, value)
        logger.info("=== END ENVIRONMENT VARIABLES ===")
    except Exception:
        pass

    return _create_app(_enable_ui)

def _create_app(enable_ui: bool = True) -> FastAPI:

    from contextlib import asynccontextmanager

    enable_worker_api = os.environ.get("NOETL_ENABLE_WORKER_API", "false").lower() in ("1", "true", "yes", "y")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if enable_worker_api:
            try:
                register_worker_pool_from_env()
            except Exception as e:
                logger.warning(f"Worker pool self-registration failed: {e}")
        try:
            from noetl.server import register_server_from_env
        except Exception as e:
            logger.exception(f"Failed to import server self-registration: {e}. Exiting.")
            raise SystemExit(1)
        try:
            await register_server_from_env()
        except Exception as e:
            logger.exception(f"Server self-registration failed: {e}. Exiting.")
            raise SystemExit(1)
        yield

    app = FastAPI(
        title="NoETL API",
        description="NoETL API server",
        version="0.1.37",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    package_dir = Path(__file__).parent
    ui_build_path = package_dir / "ui" / "build"

    app.include_router(server_router, prefix="/api")
    app.include_router(system_router, prefix="/api/sys", tags=["System"]) 

    if enable_worker_api:
        app.include_router(worker_router, prefix="/api/worker", tags=["Worker"]) 

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    if enable_ui and ui_build_path.exists():
        @app.get("/favicon.ico", include_in_schema=False)
        async def favicon():
            favicon_file = ui_build_path / "favicon.ico"
            if favicon_file.exists():
                return FileResponse(favicon_file)
            return FileResponse(ui_build_path / "index.html")
        
        app.mount("/assets", StaticFiles(directory=ui_build_path / "assets"), name="assets")
        
        @app.get("/{catchall:path}", include_in_schema=False)
        async def spa_catchall(catchall: str):
            return FileResponse(ui_build_path / "index.html")
        
        @app.get("/", include_in_schema=False)
        async def root():
            return FileResponse(ui_build_path / "index.html")
    else:
        @app.get("/", include_in_schema=False)
        async def root_no_ui():
            return {"message": "NoETL API is running, but UI is not available"}

    return app


app = create_app()


def main():
    host = os.getenv("SERVER_HOST", "0.0.0.0")
    port = int(os.getenv("SERVER_PORT", "8080"))
    reload_flag = os.getenv("SERVER_RELOAD", "1").lower() not in ("0", "false", "no")
    access_log_flag = os.getenv("SERVER_ACCESS_LOG", os.getenv("NOETL_ACCESS_LOG", "0")).lower() in ("1", "true", "yes", "y")
    uvicorn.run(app, host=host, port=port, reload=reload_flag, access_log=access_log_flag)


if __name__ == "__main__":
    sys.exit(main() or 0)
