from fastapi import FastAPI, HTTPException, Request, Header, Response, Depends
from strawberry.fastapi import GraphQLRouter
from api_config import AppConfig
from typing import List
from loguru import logger
from natstream import NatsConnectionPool
from aioprometheus import render, Counter, Registry, REGISTRY
from api_resolvers import schema



app = FastAPI()
REGISTRY.clear()
app.registry = Registry()
app.api_requests_counter = Counter("api_requests_total", "Count of requests")
app.api_health_check_counter = Counter("api_health_checks_total", "Count of health checks")
app.api_events_counter = Counter("api_events_total", "Count of events")
app.api_errors_counter = Counter("api_errors_total", "Count of errors")
app.registry.register(app.api_requests_counter)
app.registry.register(app.api_health_check_counter)
app.registry.register(app.api_events_counter)
app.registry.register(app.api_errors_counter)

def config_context_dependency() -> AppConfig:
    return AppConfig.app_args()

async def get_context(
    config_context=Depends(config_context_dependency),
):
    return config_context

graphql_router = GraphQLRouter(schema=schema, context_getter=get_context)
app.include_router(graphql_router, prefix="/noetl")

@app.get("/")
async def get_root():
    """
    NoETL API root.
    """
    app.api_events_counter.inc({"path": "/"})
    return {"NoETL": "Workflow"}


@app.get("/metrics")
async def handle_metrics(accept: List[str] = Header(None)):
    """
    NoETL API metrics.
    """
    content, http_headers = render(app.registry, accept)
    return Response(content=content, media_type=http_headers["Content-Type"])


@app.get("/health")
async def health_check(request: Request):
    """
    NoETL API Health check.
    """
    app.api_health_check_counter.inc({"path": request.scope["path"]})
    return {
        "status": "healthy"
    }


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """
    NoETL API exception handler.
    """
    app.api_errors_counter.inc({"path": request.scope["path"]})
    return {
        "status_code": exc.status_code,
        "detail": exc.detail
    }


@app.on_event("startup")
async def on_startup():
    """
    NoETL API startup.
    """
    AppConfig.app_args()
    NatsConnectionPool(config=AppConfig.get_nats_config())
    logger.info("""NoETL API is started.""")


@app.on_event("shutdown")
async def on_shutdown():
    """
    NoETL API shutdown.
    """
    nats_pool = NatsConnectionPool.get_instance()
    await nats_pool.close_pool()
    REGISTRY.clear()


def main(config):
    import uvicorn
    try:
        config.set_log_level()
        logger.info(f"NoETL API starting with {config}.")
        uvicorn.run("api:app",
                    host=config.host,
                    port=config.port,
                    reload=config.reload,
                    workers=config.workers,
                    limit_concurrency=config.limit_concurrency,
                    limit_max_requests=config.limit_max_requests
                    )
    except Exception as e:
        logger.error(f"NoETL API error: {e}.")


if __name__ == "__main__":
    main(config=AppConfig.app_args())
