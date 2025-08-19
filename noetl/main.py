import os
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

    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.INFO
    )

    print("=== ENVIRONMENT VARIABLES AT SERVER STARTUP ===")
    for key, value in sorted(os.environ.items()):
        print(f"ENV: {key}={value}")
    print("=== END ENVIRONMENT VARIABLES ===")

    return _create_app(_enable_ui)

def _create_app(enable_ui: bool = True) -> FastAPI:

    app = FastAPI(
        title="NoETL API",
        description="NoETL API server",
        version="0.1.37"
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

    enable_worker_api = os.environ.get("NOETL_ENABLE_WORKER_API", "true").lower() in ("1", "true", "yes", "y")
    if enable_worker_api:
        app.include_router(worker_router, prefix="/api/worker", tags=["Worker"])

        @app.on_event("startup")
        async def _register_worker_pool_startup():
            try:
                register_worker_pool_from_env()
            except Exception as e:
                logger.warning(f"Worker pool self-registration failed: {e}")

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
