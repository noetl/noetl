import asyncio
from loguru import logger
import aiofiles
import yaml
from components import Workflow, Job, Task, automata


async def parse_workflow_yaml(yaml_string):
    config = yaml.safe_load(yaml_string)
    workflow_config = config["workflow"]
    variables = workflow_config["variables"]
    workflow_name = workflow_config["name"]
    jobs = []
    automata.set_value(f"{workflow_name}.variables", variables)
    automata.set_value(f"{workflow_name}.status", "ready")
    for job_config in workflow_config["jobs"]:
        job_name = job_config["name"]
        automata.set_value(f"{workflow_name}.jobs.{job_name}.status", "ready")
        tasks = []
        for task_config in job_config["tasks"]:
            task_name = task_config["name"]
            automata.set_value(f"{workflow_name}.jobs.{job_name}.tasks.{task_name}.status", "ready")
            automata.set_value(f"{workflow_name}.jobs.{job_name}.tasks.{task_name}.output", {})
            task = Task(**task_config, workflow_name=workflow_name, job_name=job_name,
                        variables=variables)
            tasks.append(task)
        job = Job(workflow_name=workflow_name, name=job_name, tasks=tasks, runtime=job_config.get("runtime"),
                  conditions=job_config.get("conditions"))
        jobs.append(job)

    workflow = Workflow(name=workflow_name, jobs=jobs, schedule=workflow_config.get("schedule"),
                        variables=variables)
    return workflow


async def main():
    async with aiofiles.open("example_workflow.yaml", "r") as f:
        yaml_config = await f.read()

    workflow = await parse_workflow_yaml(yaml_config)
    logger.info(workflow)
    logger.info(f"automata: {automata}")
    await workflow.execute()
    logger.info(f"automata: {automata}")


if __name__ == "__main__":
    asyncio.run(main())
