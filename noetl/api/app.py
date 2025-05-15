import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from noetl.util import setup_logger
from noetl.connectors.hub import ConnectorHub, get_connector_hub
log_name = os.path.splitext(os.path.relpath(__file__, start=os.getcwd()).replace(os.sep, "."))[0]
logger = setup_logger(log_name, include_location=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app_context: ConnectorHub | None = None
    try:
        logger.info("NoETL service starting.")
        app_context = await get_connector_hub()
        await app_context.initialize_gs()
        logger.info("NoETL components initialized.")
        logger.info("NoETL service started.")
        yield
    except Exception as e:
        logger.critical(f"Startup error: {e}", exc_info=True)
        raise
    finally:
        if app_context:
            try:
                await app_context.cleanup()
            except Exception as e:
                logger.error(f"NoETL shutdown error: {e}.", exc_info=True)
        logger.info("NoETL service stopped.")



def create_app(host: str = "0.0.0.0", port: int = 8082) -> FastAPI:
    from noetl.config.settings import AppConfig
    app_config = AppConfig()
    app_config.noetl_url = f"http://{host}:{port}"

    app = FastAPI(
        title="NoETL API",
        description="NoETL SERVICE API",
        version="0.0.2",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_routers(app)
    app.mount("/static", StaticFiles(directory=app_config.static_dir), name="static")
    return app


def register_routers(app: FastAPI):
    import importlib
    import pkgutil
    from noetl.api import routes
    package = routes

    for _, module_name, _ in pkgutil.iter_modules(package.__path__):
        _module_name = f"{package.__name__}.{module_name}"
        module = importlib.import_module(_module_name)
        if hasattr(module, "router"):
            app.include_router(getattr(module, "router"))
        else:
            logger.warning(f"APIRouter is missing in {_module_name} module.")
