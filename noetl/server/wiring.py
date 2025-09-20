"""
Server wiring: FastAPI app creation, DI, and configuration skeleton.
"""

from fastapi import FastAPI
from noetl.api.routers import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(title="NoETL API")
    app.include_router(api_router, prefix="/api")

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok"}

    return app

