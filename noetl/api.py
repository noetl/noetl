from fastapi import FastAPI, Depends, HTTPException, Request, Header, Response
from pydantic import BaseModel
from typing import List
import spacy
from loguru import logger
import argparse
from natstream import NatsConnectionPool
from config import Config
from record import Record
from aioprometheus import render, Counter, Registry, REGISTRY


class ApiConfig(BaseModel):
    nats_url: str = "nats://localhost:32645"
    nats_pool_size: int = 10
    host: str = "localhost"
    port: int = 8021
    reload: bool = False
    workers: int = 1
    limit_concurrency: int = 100
    limit_max_requests: int = 100

    def update(self, args):
        if args.nats_url:
            self.nats_url = args.nats_url
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


class CommandValidationResult(BaseModel):
    is_valid: bool = False
    function_name: str | None = None
    message: str | None = None


class Command(BaseModel):
    tokens: str
    metadata: dict
    payload: dict


def get_nats_pool():
    return nats_pool


app = FastAPI()
REGISTRY.clear()
app.registry = Registry()
app.api_commands_counter = Counter("api_commands", "Count of commands")
app.api_health_check_counter = Counter("api_health_checks", "Count of health checks")
app.api_events_counter = Counter("api_events", "Count of events")
app.api_errors_counter = Counter("api_errors", "Count of errors")

app.registry.register(app.api_commands_counter)
app.registry.register(app.api_health_check_counter)
app.registry.register(app.api_events_counter)
app.registry.register(app.api_errors_counter)


@app.get("/metrics")
async def handle_metrics(accept: List[str] = Header(None)):
    content, http_headers = render(app.registry, accept)
    return Response(content=content, media_type=http_headers["Content-Type"])


nlp = spacy.load("en_core_web_sm")
api_config: ApiConfig = ApiConfig()
nats_pool: NatsConnectionPool | None = None


@app.get("/")
async def get_root():
    app.api_events_counter.inc({"path": "/"})
    return {"Hello": "Workflow"}


@app.get("/test")
async def test(nats_pool: NatsConnectionPool = Depends(get_nats_pool)):
    async with nats_pool.connection() as js:
        ack = await js.publish('test.greeting', b'Hello TestDrivenDevelopment!')
        logger.info(f'Ack: stream={ack.stream}, sequence={ack.seq}')

        async def cb(msg):
            logger.info(msg)
            await msg.ack()

        await js.subscribe('test.greeting', cb=cb)
        foo = await js.subscribe('test.greeting', cb=cb, durable='foo')
        bar = await js.subscribe('test.greeting', durable='bar')
        workers = await js.subscribe('test.greeting', 'workers', cb=cb)
        logger.info(f"{foo._id}, {bar._id}, {workers._id}")
        await foo.unsubscribe()
        await bar.unsubscribe()
        await workers.unsubscribe()
        return ack.seq


def validate_command(command_text):
    doc = nlp(command_text.lower())
    tokens = [token.text for token in doc]

    if not tokens:
        return False, None, None

    command_structures = {
        "add_workflow_config": ["add", "workflow", "config", str],
    }

    for function_name, structure in command_structures.items():
        if len(tokens) == len(structure):
            is_valid = all(t1 == t2 or isinstance(t2, type) and isinstance(t1, t2)
                           for t1, t2 in zip(tokens, structure))
            if is_valid:
                return CommandValidationResult(is_valid=True, function_name=function_name,
                                               message=" ".join(tokens[len(structure):]))

    return CommandValidationResult()


async def add_workflow_config(command: Command):
    try:
        workflow_config = Config.create(command.payload)
        logger.info(workflow_config)
        record = Record.create(
            name=workflow_config.get_value("metadata.name"),
            kind=workflow_config.get_value("kind"),
            metadata=command.metadata,
            reference=None,
            payload=workflow_config
        )
        return record

    except Exception as e:
        logger.error(f"NoETL API workflow config error: {str(e)}.")


@app.post("/command/")
async def add_command(
        command: Command,
        request: Request,
        nats_pool: NatsConnectionPool = Depends(get_nats_pool)
):
    logger.info(command)
    app.api_commands_counter.inc({"path": request.scope["path"]})
    command_validation_result: CommandValidationResult = validate_command(command.tokens)
    if command_validation_result.function_name == "add_workflow_config":
        record = await add_workflow_config(command)
        async with nats_pool.connection() as js:
            ack = await js.publish(f"command.api.add.workflow.{record.identifier}", record.serialize())
            logger.info(f"Ack: stream={ack.stream}, sequence={ack.seq}, Identifier={record.identifier}")
        return {"message": f"Command added. Identifier: {record.identifier}, stream={ack.stream}, sequence={ack.seq}"}
    return {"message": f"Command IS NOT added {command}."}


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
    global nats_pool
    nats_pool = NatsConnectionPool(
        url=api_config.nats_url,
        size=api_config.nats_pool_size
    )
    logger.info("""NoETL API is starting...""")


@app.on_event("shutdown")
async def on_shutdown():
    global nats_pool
    await nats_pool.close_pool()
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
