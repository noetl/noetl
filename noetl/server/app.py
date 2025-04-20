import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from noetl.shared import setup_logger, app_context, AppContext
from noetl.server.api.main_routes import router as main_router
log_name = (
    os.path.splitext(
        os.path.relpath(__file__, start=os.getcwd())
        .replace(os.sep, ".")
    )[0]
)
logger = setup_logger(log_name, include_location=True)


@asynccontextmanager
async def lifespan(app: FastAPI):

    try:
        from noetl.shared import app_context
        app_context: AppContext = await app_context()
        await app_context.initialize_gs()
        logger.info("NoETL service started.")
        yield

    except Exception as e:
        logger.critical(f"Startup error: {e}", exc_info=True)
        raise

    finally:
        from noetl.shared import app_context
        try:
            app_context: AppContext = await app_context()
            await app_context.cleanup()
        except Exception as e:
            logger.error(f"NoETL error during shutdown: {e}", exc_info=True)
        logger.info("NoETL stopped.")


def create_app() -> FastAPI:
    app = FastAPI(
        title="NoETL API",
        description="NoETL workflow service",
        version="0.0.2",
        lifespan=lifespan
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_routers(app)
    return app


def register_routers(app: FastAPI):
    app.include_router(main_router, prefix="", tags=["NoETL"])