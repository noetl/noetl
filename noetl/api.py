from fastapi import FastAPI, HTTPException, Request, Header, Response
from strawberry.fastapi import GraphQLRouter
from pydantic import BaseModel
from typing import List
from loguru import logger
import argparse
from natstream import NatsConnectionPool, NatsConfig, initialize_nats_pool, get_nats_pool
from aioprometheus import render, Counter, Registry, REGISTRY
from apigql import schema


class ApiConfig(BaseModel):
    nats_config: NatsConfig = NatsConfig(nats_url="nats://localhost:32645", nats_pool_size=10)
    host: str = "localhost"
    port: int = 8021
    reload: bool = False
    workers: int = 1
    limit_concurrency: int = 100
    limit_max_requests: int = 100

    def update(self, args):
        if args.nats_url:
            self.nats_config.nats_url = args.nats_url
        if args.host:
            self.host = args.host
        if args.port:
            self.port = int(args.port)
        if args.reload:
            self.reload = args.reload
        if args.workers:
            self.workers = int(args.workers)
        if args.limit_concurrency:
            self.limit_concurrency = int(args.limit_concurrency)
        if args.limit_max_requests:
            self.limit_max_requests = int(args.limit_max_requests)


app = FastAPI()
REGISTRY.clear()
app.registry = Registry()
app.api_commands_counter = Counter("api_commands_total", "Count of commands")
app.api_health_check_counter = Counter("api_health_checks_total", "Count of health checks")
app.api_events_counter = Counter("api_events_total", "Count of events")
app.api_errors_counter = Counter("api_errors_total", "Count of errors")

app.registry.register(app.api_commands_counter)
app.registry.register(app.api_health_check_counter)
app.registry.register(app.api_events_counter)
app.registry.register(app.api_errors_counter)

graphql_router = GraphQLRouter(schema=schema)
app.include_router(graphql_router, prefix="/noetl")
api_config: ApiConfig = ApiConfig()
nats_pool: NatsConnectionPool | None = None


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
    global api_config
    await initialize_nats_pool(nats_config=api_config.nats_config)
    logger.info("""NoETL API is starting...""")


@app.on_event("shutdown")
async def on_shutdown():
    pool = get_nats_pool()
    await pool.close_connections()
    REGISTRY.clear()


def main(args):
    global api_config
    api_config.update(args)
    try:
        logger.info(f"Starting NoETL API {args}")
        uvicorn.run("api:app",
                    host=api_config.host,
                    port=api_config.port,
                    reload=api_config.reload,
                    workers=api_config.workers,
                    limit_concurrency=api_config.limit_concurrency,
                    limit_max_requests=api_config.limit_max_requests
                    )
    except Exception as e:
        logger.error(f"NoETL API error: {e}")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="FastAPI Command API")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", default="8021", help="Port to listen on (default: 8021)")
    parser.add_argument("--workers", default="1", help="Number of workers (default: 1)")
    parser.add_argument("--reload", action='store_true', help="Enable auto-reload (default: disabled)")
    parser.add_argument("--limit_concurrency", default="100", help="Limit concurrency (default: 100)")
    parser.add_argument("--limit_max_requests", default="100", help="Limit max requests (default: 100)")
    parser.add_argument("--nats_url", default="nats://localhost:32645", help="nats://<host>:<port>")
    main(parser.parse_args())
