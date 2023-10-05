from fastapi import FastAPI, Depends, HTTPException
from pydantic import BaseModel
import os
import spacy
import json
from loguru import logger
import argparse
from nats.aio.client import Client
from natstream import NatsConnectionPool

nlp = spacy.load("en_core_web_sm")
app = FastAPI()
nats_pool = NatsConnectionPool(url="nats://localhost:30518", size=5)
@app.get("/test")
async def test():
    async def func(js):
        await js.add_stream(name='hello', subjects=['hello'])
        ack = await js.publish('hello', b'Hello JS!')
        logger.info(f'Ack: stream={ack.stream}, sequence={ack.seq}')

    return await nats_pool.execute(func)
# nats_pool = NatsConnectionPool(size=5)


# class NatsJetStream:
#     async def __aenter__(self):
#         self.nc = await nats.connect("nats://localhost:4222")
#         self.js = self.nc.jetstream()
#         return self.js
#
#     async def __aexit__(self, exc_type, exc_value, traceback):
#         await self.nc.close()
#

class CommandValidationResult(BaseModel):
    is_valid: bool
    function_name: str
    message: str


class Command(BaseModel):
    name: str
    data: dict


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
                return True, function_name, " ".join(tokens[len(structure):])

    return False, None, None


@app.post("/validate_command/")
async def validate_command_endpoint(command: Command):
    is_valid, function_name, message = validate_command(command["name"])
    if not is_valid:
        return {"is_valid": False}
    return {"is_valid": True, "function_name": function_name, "message": message}


# @app.post("/command/")
# async def add_command(
#         command: Command,
#         nc: Client = Depends(lambda: nats_connection)
#     ):
#     js = nc.jetstream()
#     command_subject = "commands." + command.name
#     await js.publish(command_subject, json.dumps(command.dict()).encode())
#     return {"message": "Command added to the queue"}

@app.get("/health")
async def health_check():
    """
    Command API Health check.
    """
    return {"status": "healthy"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """
    Command API exception handler.
    """
    return {"status_code": exc.status_code, "detail": exc.detail}


@app.on_event("startup")
async def on_startup():
    logger.info("""Starting NoETL API""")


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("""Shutting down NoETL API""")
    await nats_pool.close_all()


def main(args):
    try:
        logger.info(f"Starting Command API application with args {args}")
        uvicorn.run("api:app",
                    host=args.host,
                    port=int(args.port),
                    reload=False,
                    workers=int(args.workers),
                    limit_concurrency=int(args.limit_concurrency),
                    limit_max_requests=int(args.limit_max_requests)
                    )
    except Exception as e:
        logger.error(f"Command API error: {e}")


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="FastAPI Command API")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind (default: 0.0.0.0)")
    parser.add_argument("--port", default="8021", help="Port to listen on (default: 8021)")
    parser.add_argument("--workers", default="3", help="Number of workers (default: 1)")
    parser.add_argument("--limit_concurrency", default="100", help="Limit concurrency (default: 1)")
    parser.add_argument("--limit_max_requests", default="100", help="Limit max requests (default: 1)")
    args = parser.parse_args()
    main(args)
