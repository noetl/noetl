import asyncio
import subprocess
import aiohttp
from typing import Optional
from loguru import logger
from workflow_engine.src.components.finite_automata import FiniteAutomata


class Task(FiniteAutomata):
    """
    A Task class that represents a single task instance within a Job and inherits from the FiniteAutomata class.
    Args:
        workflow_name (str): The name of the parent Workflow.
        job_name (str): The name of the parent Job.
        instance_id (str): The unique instance ID of the parent Workflow.
        task_config (dict): A dictionary containing the parsed task configuration.
    """
    def __init__(self,
                 workflow_name: str,
                 job_name: str,
                 instance_id: str,
                 task_config: dict
                 ):
        """
        Initializes a new Task instance based on the provided configuration.
        Args:
            workflow_name (str): The name of the parent Workflow.
            job_name (str): The name of the parent Job.
            instance_id (str): The unique instance ID of the parent Workflow.
            task_config (dict): A dictionary containing the parsed task configuration.
        """
        super().__init__(name=task_config.get("name"), instance_id=instance_id,
                         conditions=task_config.get("conditions"))
        self.workflow_name: str = workflow_name
        self.job_name: str = job_name
        self.variables: Optional[dict] = task_config.get("variables")
        self.kind: str = task_config.get("kind")
        self.command: Optional[str] = task_config.get("command")
        self.method: Optional[str] = task_config.get("method")
        self.url: Optional[str] = task_config.get("url")
        self.timeout: Optional[str] = task_config.get("timeout")
        self.loop: Optional[dict] = task_config.get("loop")
        self.status = None
        self.output = None

    async def execute(self):
        """
         Executes the Task instance based on its kind. The supported kinds are 'shell' and 'rest_api'.
         Sets the Task state to RUNNING and logs the execution process.
         """
        self.set_state("running")
        logger.info(f"Executing task {self.name}")
        # if self.conditions and not self.check_conditions():
        #     logger.info(f"Skipping task {self.name} due to unmet conditions")
        #     return
        if self.kind == 'shell':
            await self.execute_shell()
        elif self.kind == 'rest_api':
            await self.execute_rest_api()
        else:
            logger.info(f"Unknown kind for task {self.name}")

    # def check_conditions(self):
    #
    #     for condition in self.conditions:
    #         template = automata.evaluate_input(condition)
    #         logger.info(f"{self.name} condition {template}")
    #         if not eval(template):
    #             return False
    #     return True

    async def execute_shell(self):
        """
        Executes the Task instance as a shell command.
        Logs the task completion status and output.
        """
        process = await asyncio.create_subprocess_shell(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await process.communicate()
        self.output = stdout.decode().strip()
        #automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.output", self.output)
        self.status = 'success' if process.returncode == 0 else 'failure'
        #automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.status", self.status)
        logger.info(f"Task {self.name} completed with status: {self.status} output: {self.output}")

    async def execute_rest_api(self):
        """
        Executes the Task instance as a REST API request.
        Logs the task completion status.
        """
        async with aiohttp.ClientSession() as session:
            async with session.request(self.method, self.url) as response:
                self.output = await response.text()
                #automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.output", self.output)
                self.status = 'success' if response.status == 200 else 'failure'
                #automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.status", self.status)
                logger.info(f"Task {self.name} completed with status {self.status}")
