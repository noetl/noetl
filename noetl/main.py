from noetl.common import setup_logger
import uvicorn
import typer
import os
import sys
import time
import socket
import signal
import subprocess
import json
import logging
import base64
import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from noetl.server import router as server_router
from noetl.common import deep_merge
from noetl.agent import NoETLAgent

logger = setup_logger(__name__, include_location=True)

app = typer.Typer()

@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    host: str = typer.Option(None, help="Server host."),
    port: int = typer.Option(None, help="Server port."),
    reload: bool = typer.Option(None, help="Server auto-reload (development)."),
    force: bool = typer.Option(None, help="Force start by killing any process using the port.")
):
    if ctx.invoked_subcommand is None and (host is not None or port is not None or reload is not None or force is not None):
        host = host or "0.0.0.0"
        port = port or 8082
        reload = reload or False
        force = force or False
        create_server(host=host, port=port, reload=reload, force=force)

def is_port_available(port, host='0.0.0.0'):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except socket.error:
        return False
    finally:
        sock.close()

def kill_process_on_port(port):
    logger.info(f"Checking for processes using port {port}...")
    if is_port_available(port):
        logger.info(f"Port {port} is already available")
        return True

    logger.info(f"Port {port} is in use. Attempting to kill the process...")

    try:
        if sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
            cmd = f"lsof -i :{port} -t"
            try:
                output = subprocess.check_output(cmd, shell=True).decode().strip()

                if output:
                    pids = output.split('\n')
                    killed = False

                    for pid in pids:
                        if pid.strip():
                            logger.info(f"Killing process {pid} using port {port}")
                            try:
                                os.kill(int(pid), signal.SIGTERM)
                                time.sleep(1)
                                try:
                                    os.kill(int(pid), 0)
                                    logger.info(f"Process {pid} did not terminate, sending SIGKILL")
                                    os.kill(int(pid), signal.SIGKILL)
                                except OSError:
                                    logger.info(f"Process {pid} terminated successfully")

                                killed = True
                            except OSError as e:
                                logger.warning(f"Error killing process {pid}: {e}")

                    if is_port_available(port):
                        logger.info(f"Port {port} is now available")
                        return True
                    else:
                        logger.warning(f"Port {port} is still in use after killing processes")
                        return False
            except subprocess.CalledProcessError as e:
                logger.warning(f"Error running lsof command: {e}. lsof might not be installed.")
                time.sleep(2)
                if is_port_available(port):
                    logger.info(f"Port {port} is now available")
                    return True
        elif sys.platform.startswith('win'):
            cmd = f"netstat -ano | findstr :{port}"
            output = subprocess.check_output(cmd, shell=True).decode()

            if output:
                lines = output.strip().split('\n')
                killed = False

                for line in lines:
                    if f":{port}" in line and "LISTENING" in line:
                        pid = line.strip().split()[-1]
                        logger.info(f"Killing process {pid} using port {port}")
                        try:
                            result = subprocess.call(f"taskkill /F /PID {pid}", shell=True)
                            if result == 0:
                                logger.info(f"Process {pid} terminated successfully")
                                killed = True
                            else:
                                logger.warning(f"Failed to kill process {pid}")
                        except Exception as e:
                            logger.warning(f"Error killing process {pid}: {e}")

                if is_port_available(port):
                    logger.info(f"Port {port} is now available")
                    return True
                else:
                    logger.warning(f"Port {port} is still in use after killing processes")
                    return False

        logger.warning(f"Could not find or kill process using port {port}")
        if is_port_available(port):
            logger.info(f"Port {port} is now available")
            return True
        return False
    except Exception as e:
        logger.error(f"Error killing process on port {port}: {e}")
        if is_port_available(port):
            logger.info(f"Port {port} is now available despite errors")
            return True
        return False

def create_app(host: str = "0.0.0.0", port: int = 8082) -> FastAPI:
    app = FastAPI(
        title="NoETL API",
        description="API for NoETL operations",
        version="0.1.0"
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(server_router)

    @app.get("/")
    async def root():
        return {"message": "Welcome to NoETL API"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app

@app.command("server")
def create_server(
    host: str = typer.Option("0.0.0.0", help="Server host."),
    port: int = typer.Option(8082, help="Server port."),
    reload: bool = typer.Option(False, help="Server auto-reload (development)."),
    force: bool = typer.Option(False, help="Force start by killing any process using the port.")
):
    if not is_port_available(port, host):
        if force:
            logger.warning(f"Port {port} is already in use. Attempting to kill the process...")
            if not kill_process_on_port(port):
                logger.error(f"Failed to free up port {port}. Cannot start server.")
                logger.error(f"Try using a different port with --port option.")
                return
        else:
            logger.error(f"Port {port} is already in use. Use --force to kill the process or try a different port.")
            return

    app = create_app(host=host, port=port)
    logger.info(f"Starting NoETL API server at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, reload=reload)

@app.command("agent")
def run_agent(
    file: str = typer.Option(..., "--file", "-f", help="Path to playbook YAML file"),
    mock: bool = typer.Option(False, help="Run in mock mode"),
    output: str = typer.Option("json", "--output", "-o", help="Output format (json or plain)"),
    export: str = typer.Option(None, help="Export execution data to Parquet file"),
    mlflow: bool = typer.Option(False, help="Use ML model for workflow control"),
    pgdb: str = typer.Option(None, help="PostgreSQL connection string"),
    input: str = typer.Option(None, help="Path to JSON file with input payload for the playbook"),
    payload: str = typer.Option(None, help="JSON string with input payload for the playbook"),
    merge: bool = typer.Option(False, help="Whether to merge the input payload with the workload section (default: False, which means override)"),
    debug: bool = typer.Option(False, help="Debug logging level")
):
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.DEBUG if debug else logging.INFO
    )

    try:
        input_payload = None
        if input:
            try:
                with open(input, 'r') as f:
                    input_payload = json.load(f)
                logger.info(f"Loaded input payload from {input}")
            except Exception as e:
                logger.error(f"Error loading input payload: {e}")
                raise typer.Exit(code=1)
        elif payload:
            try:
                input_payload = json.loads(payload)
                logger.info("Parsed input payload from command line")
            except Exception as e:
                logger.error(f"Error parsing payload JSON: {e}")
                raise typer.Exit(code=1)

        pgdb_conn = pgdb or os.environ.get("NOETL_PGDB")
        if not pgdb_conn:
            pgdb_conn = "dbname=noetl user=noetl password=noetl host=localhost port=5434"
            logger.info(f"Using default PostgreSQL connection string: {pgdb_conn}")

        agent = NoETLAgent(file, mock_mode=mock, pgdb=pgdb_conn)
        workload = agent.playbook.get('workload', {})

        if input_payload:
            if merge:
                logger.info("Merge mode: deep merging input payload with workload")
                merged_workload = deep_merge(workload, input_payload)
                for key, value in merged_workload.items():
                    agent.update_context(key, value)
                agent.update_context('workload', merged_workload)
                agent.store_workload(merged_workload)
            else:
                logger.info("Override mode: replacing specific workload keys with input payload")
                new_workload = workload.copy()
                for key, value in input_payload.items():
                    new_workload[key] = value
                for key, value in new_workload.items():
                    agent.update_context(key, value)
                agent.update_context('workload', new_workload)
                agent.store_workload(new_workload)
        else:
            logger.info("Using default workload from playbook")
            for key, value in workload.items():
                agent.update_context(key, value)
            agent.update_context('workload', workload)
            agent.store_workload(workload)

        results = agent.run(mlflow=mlflow)

        if export:
            agent.export_execution_data(export)

        if output == "json":
            logger.info(json.dumps(results, indent=2))
        else:
            for step, result in results.items():
                logger.info(f"{step}: {result}")

        logger.info(f"PostgreSQL connection: {agent.pgdb}")
        logger.info(f"Open notebook/agent_mission_report.ipynb and set 'pgdb' to {agent.pgdb}")

    except Exception as e:
        logger.error(f"Error executing playbook: {e}", exc_info=True)
        print(f"Error executing playbook: {e}")
        raise typer.Exit(code=1)

@app.command("playbook")
def manage_playbook(
    register: str = typer.Option(None, "--register", "-r", help="Path to playbook YAML file to register"),
    execute: bool = typer.Option(False, "--execute", "-e", help="Execute a playbook by path"),
    path: str = typer.Option(None, "--path", help="Path of the playbook to execute"),
    version: str = typer.Option(None, "--version", "-v", help="Version of the playbook to execute (if omitted, latest version will be used)"),
    input: str = typer.Option(None, "--input", "-i", help="Path to JSON file with input payload for the playbook"),
    payload: str = typer.Option(None, "--payload", help="JSON string with input payload for the playbook"),
    host: str = typer.Option("localhost", "--host", help="NoETL server host"),
    port: int = typer.Option(8082, "--port", "-p", help="NoETL server port"),
    sync_to_postgres: bool = typer.Option(True, "--sync-to-postgres", help="Whether to sync execution data to PostgreSQL"),
    merge: bool = typer.Option(False, "--merge", help="Whether to merge the input payload with the workload section (default: False, which means override)")
):
    if register:
        try:
            if not os.path.exists(register):
                logger.error(f"File not found: {register}")
                raise typer.Exit(code=1)
            with open(register, 'r') as f:
                content = f.read()
            content_base64 = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            url = f"http://{host}:{port}/catalog/register"
            headers = {"Content-Type": "application/json"}
            data = {"content_base64": content_base64}
            logger.info(f"Registering playbook {register} with NoETL server at {url}")
            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Playbook registered successfully: {result}")
                logger.info(f"Resource path: {result.get('resource_path')}")
                logger.info(f"Resource version: {result.get('resource_version')}")
            else:
                logger.error(f"Failed to register playbook: {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error registering playbook: {e}")
            raise typer.Exit(code=1)
    elif execute:
        try:
            if not path:
                logger.error("Path is required when using --execute")
                logger.info("Example: noetl playbook --execute --path weather_example --version 0.1.0")
                raise typer.Exit(code=1)

            input_payload = {}
            if input:
                try:
                    with open(input, 'r') as f:
                        input_payload = json.load(f)
                    logger.info(f"Loaded input payload from {input}")
                except Exception as e:
                    logger.error(f"Error loading input payload from file: {e}")
                    raise typer.Exit(code=1)
            elif payload:
                try:
                    input_payload = json.loads(payload)
                    logger.info("Parsed input payload from command line")
                except Exception as e:
                    logger.error(f"Error parsing payload JSON: {e}")
                    raise typer.Exit(code=1)

            url = f"http://{host}:{port}/agent/execute"
            headers = {"Content-Type": "application/json"}
            data = {
                "path": path,
                "input_payload": input_payload,
                "sync_to_postgres": sync_to_postgres,
                "merge": merge
            }

            if version:
                data["version"] = version

            if version:
                logger.info(f"Executing playbook {path} version {version} on NoETL server at {url}")
            else:
                logger.info(f"Executing playbook {path} (latest version) on NoETL server at {url}")
            response = requests.post(url, headers=headers, json=data)

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Playbook executed successfully")

                if result.get("status") == "success":
                    logger.info(f"Execution ID: {result.get('execution_id')}")
                    logger.info(f"Result: {json.dumps(result.get('result'), indent=2)}")
                else:
                    logger.error(f"Execution failed: {result.get('error')}")
                    raise typer.Exit(code=1)
            else:
                logger.error(f"Failed to execute playbook: {response.status_code}")
                logger.error(f"Response: {response.text}")
                raise typer.Exit(code=1)

        except Exception as e:
            logger.error(f"Error executing playbook: {e}")
            raise typer.Exit(code=1)
    else:
        logger.info("No action specified. Use --register to register a playbook or --execute to execute a playbook.")
        logger.info("Examples:")
        logger.info("  noetl playbook --register ./catalog/playbooks/weather_example.yaml")
        logger.info("  noetl playbook --execute --path weather_example --version 0.1.0 --payload '{\"city\": \"New York\"}'")
        logger.info("  noetl playbook --execute --path weather_example --input ./data/input/payload.json")

def main():
    app()

if __name__ == "__main__":
    app()
