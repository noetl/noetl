import asyncio
import aiohttp
import aiofiles
import yaml
import subprocess
from typing import Dict, Any


async def execute_workflow(yaml_config: str):
    config = yaml.safe_load(yaml_config)
    workflow = config["workflow"]

    jobs = workflow["jobs"]
    job_tasks = [execute_job(job) for job in jobs]
    await asyncio.gather(*job_tasks)


async def execute_job(job: Dict[str, Any]):
    tasks = job["tasks"]
    task_tasks = [execute_task(task) for task in tasks]
    await asyncio.gather(*task_tasks)


async def execute_task(task: Dict[str, Any]):
    if task["type"] == "shell":
        await execute_shell_task(task)
    elif task["type"] == "rest_api":
        await execute_rest_api_task(task)


async def execute_shell_task(task: Dict[str, Any]):
    process = await asyncio.create_subprocess_shell(
        task["script"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    print(f"Task {task['name']} stdout: {stdout.decode()}")
    print(f"Task {task['name']} stderr: {stderr.decode()}")


async def execute_rest_api_task(task: Dict[str, Any]):
    async with aiohttp.ClientSession() as session:
        async with session.request(task["method"], task["url"]) as response:
            text = await response.text()
            print(f"Task {task['name']} response: {text}")


async def main():
    async with aiofiles.open("example_workflow.yaml", "r") as f:
        yaml_config = await f.read()

    await execute_workflow(yaml_config)


if __name__ == "__main__":
    asyncio.run(main())
