from string import Template

class Task:
    def __init__(self, status, output):
        self.status = status
        self.output = output

    def to_dict(self):
        return {
            'status': self.status,
            'output': self.output
        }

previous_task = Task('success', 'some output')

condition = "'${previous_task.status}' == 'success'"

context = {'previous_task': previous_task.to_dict()}
print(context)
# formatted_condition = Template(condition).substitute(context)
# print(formatted_condition)
# result = eval(formatted_condition)
#
# print(result)  # True

import re

# def replace_template(template: str, replacement: str, input_string: str):
#     return re.sub(r"{{\s*" + re.escape(template) + r"\s*}}", replacement, input_string)
#
# input_string = "The status of the previous task is {{ previous_task.status }}."
#
# replacement = "success"
#
# output = replace_template("previous_task.status", replacement, input_string)
#
# print(output)  # The status of the previous task is success.



import re

def extract_content(input_string: str):
    pattern = r"{{\s*(.*?)\s*}}"
    matches = re.findall(pattern, input_string)
    return matches

input_string = "The status of the previous task is '{{ previous_task.status }}' and the output is {{ previous_task.output }} {{ next.output}}."

extracted_content = extract_content(input_string)

print(extracted_content)  # ['previous_task.status', 'previous_task.output']

def get_nested_value(dct, path_str):
    keys = path_str.split(".")
    value = dct
    for key in keys:
        value = value.get(key)
        if value is None:
            return None
    return value

nested_dict = {"a": {"b": {"c": 42}}}
path = "a.b.c"

result = get_nested_value(nested_dict, path)
print(result)  # Output: 42


result_42 = get_nested_value(context,'previous_task.status')
print(result_42)

import re


def extract_content(input_string: str):
    pattern = r"{{\s*(.*?)\s*}}"
    matches = re.findall(pattern, input_string)
    return matches


def replace_match(match):
    print(f"mathc: {match}" )
    replacements = {
        "previous_task.status": "success",
        "previous_task.output": "Some output",
        "next.output": "Next output"
    }

    key = match.group(1)
    return replacements.get(key, "")


input_string = "The status of the previous task is '{{ previous_task.status }}' and the output is {{ previous_task.output }} {{ next.output}}."

output_string = re.sub(r"{{\s*(.*?)\s*}}", replace_match, input_string)
print('hi')
print(output_string)


###############################
""""workflow_executor.py"""

import asyncio
import aiohttp
import aiofiles
import yaml
import subprocess
from typing import Dict, Any, List
from croniter import croniter
from datetime import datetime
from loguru import logger

job_statuses = {}


async def execute_workflow(yaml_config: str):
    config = yaml.safe_load(yaml_config)
    workflow = config["workflow"]

    jobs = workflow["jobs"]
    for job in jobs:
        job_statuses[job["name"]] = "pending"

    while any(status == "pending" for status in job_statuses.values()):
        job_tasks = [execute_job(job) for job in jobs if job_ready(job)]
        await asyncio.gather(*job_tasks)

        await asyncio.sleep(1)  # Check every second if jobs are ready to execute


def job_ready(job: Dict[str, Any]) -> bool:
    if job_statuses[job["name"]] != "pending":
        return False

    if "schedule" in job:
        now = datetime.now()
        iter = croniter(job["schedule"], now)
        next_scheduled_time = iter.get_next(datetime)
        logger.info(f"Next scheduled time {next_scheduled_time}")
        if next_scheduled_time > now:
            return False

    if "dependencies" in job:
        for dependency in job["dependencies"]:
            if job_statuses.get(dependency) != "completed":
                return False

    return True


async def execute_job(job: Dict[str, Any]):
    tasks = job["tasks"]
    job_statuses[job["name"]] = "running"
    task_results = []

    for task in tasks:
        conditions_met = check_conditions(task, task_results)
        if conditions_met:
            result = await execute_task(task)
            task_results.append(result)

    job_statuses[job["name"]] = "completed"


def check_conditions(task: Dict[str, Any], task_results: List[Dict[str, Any]]) -> bool:
    if "conditions" in task:
        for condition in task["conditions"]:
            if not eval(condition, {"previous_task": task_results[-1] if task_results else None}):
                return False

    return True


async def execute_task(task: Dict[str, Any]) -> Dict[str, Any]:
    if task["type"] == "shell":
        return await execute_shell_task(task)
    elif task["type"] == "rest_api":
        return await execute_rest_api_task(task)


async def execute_shell_task(task: Dict[str, Any]) -> Dict[str, Any]:
    process = await asyncio.create_subprocess_shell(
        task["script"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    print(f"Task {task['name']} stdout: {stdout.decode()}")
    print(f"Task {task['name']} stderr: {stderr.decode()}")

    return {"status": "success" if process.returncode == 0 else "failed", "output": stdout.decode()}


async def execute_rest_api_task(task: Dict[str, Any]) -> Dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        async with session.request(task["method"], task["url"]) as response:
            text = await response.text()
            print(f"Task {task['name']} response: {text}")

            return {"status": "success" if response.status == 200 else "failed", "output": text}


async def main():
    async with aiofiles.open("coordinatorworkflow_1.yaml", "r") as f:
        yaml_config = await f.read()

    await execute_workflow(yaml_config)

def check_true(val = None):
    if val:
        return True
    return False

if __name__ == "__main__":
    #asyncio.run(main())
    print(check_true())
