import os
import shutil
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import spacy
from loguru import logger
import argparse

nlp = spacy.load("en_core_web_sm")
app = FastAPI()


class CommandValidationResult(BaseModel):
    is_valid: bool
    function_name: str
    message: str


class Command(BaseModel):
    name: str
    data: dict


command_storage_folder = "command_db"
pending_folder = os.path.join(command_storage_folder, "pending")
processing_folder = os.path.join(command_storage_folder, "processing")
processed_folder = os.path.join(command_storage_folder, "processed")
failed_folder = os.path.join(command_storage_folder, "failed")
os.makedirs(pending_folder, exist_ok=True)
os.makedirs(processing_folder, exist_ok=True)
os.makedirs(processed_folder, exist_ok=True)
os.makedirs(failed_folder, exist_ok=True)


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


@app.post("/add_command/")
async def add_command(command: Command):
    command_filename = f"{command['name']}.json"
    command_path = os.path.join(pending_folder, command_filename)

    with open(command_path, "w") as f:
        f.write(command.json())

    return {"message": "Command added to the queue."}


@app.post("/process_command/")
async def process_command():
    pending_commands = os.listdir(pending_folder)

    if pending_commands:
        command_to_process = pending_commands[0]
        source_path = os.path.join(pending_folder, command_to_process)
        dest_path = os.path.join(processing_folder, command_to_process)

        shutil.move(source_path, dest_path)

        return {"message": "Command processing started."}
    else:
        return {"message": "No pending commands to process."}


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


@app.post("/shutdown")
async def shutdown():
    logger.info("""Shutting down Command API application.""")
    os.kill(os.getpid(), 9)


def main(args):
    try:
        logger.info(f"Starting Command API application with args {args}")
        uvicorn.run("command:app",
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
