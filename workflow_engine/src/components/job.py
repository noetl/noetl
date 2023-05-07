from loguru import logger
from datetime import datetime
from croniter import croniter
from workflow_engine.src.components.finite_automata import FiniteAutomata, State
from workflow_engine.src.components.task import Task


class Job(FiniteAutomata):
    """
    A Job class that represents a single job instance within a Workflow and inherits from the FiniteAutomata class.
    Args:
        workflow_name (str): The name of the parent Workflow.
        instance_id (str): The unique instance ID of the parent Workflow.
        job_config (dict): A dictionary containing the parsed job configuration.
    """
    def __init__(self, workflow_name: str, instance_id: str, job_config: dict):
        """
        Initializes a new Job instance based on the provided configuration.
        Args:
            workflow_name (str): The name of the parent Workflow.
            instance_id (str): The unique instance ID of the parent Workflow.
            job_config (dict): A dictionary containing the parsed job configuration.
        """
        super().__init__(name=job_config.get("name"), instance_id=instance_id, conditions=job_config.get("conditions"))
        self.workflow_name: str = workflow_name
        self.tasks = []
        self.runtime = job_config.get("runtime")
        self.schedule = job_config.get("runtime", "shell")
        self.define_tasks(job_config.get("tasks"))

    def define_tasks(self, job_config):
        """
        Defines tasks for the Job instance based on the provided job_config.
        Args:
            job_config: The configuration for the tasks.
        """
        for task_config in job_config:
            task = Task(
                workflow_name=self.workflow_name,
                job_name=self.name,
                instance_id=self.instance_id,
                task_config=task_config
            )
            self.tasks.append(task)

    # def get_status(self):
    #     return automata.get_value(f"{self.workflow_name}.jobs.{self.name}.status")
    #
    # def set_status(self, status):
    #     automata.set_value(f"{self.workflow_name}.jobs.{self.name}.status", status)

    async def execute(self):
        """
        Executes the Job instance by running its tasks in the order they were defined.
        Sets the Job state to RUNNING and logs the execution process.
        """
        self.set_state(State.RUNNING)
        logger.info(f"Executing job {self.name}")
        for task in self.tasks:
            await task.execute()

    def job_ready(self) -> bool:
        """
        Determines if the Job is ready to be executed based on its state and schedule.
        Returns:
            bool: True if the Job is ready to be executed, False otherwise.
        """
        if self.state == State.READY:
            return False

        if self.schedule:
            now = datetime.now()
            iter = croniter(self.schedule, now)
            next_scheduled_time = iter.get_next(datetime)
            logger.info(f"Next scheduled time {next_scheduled_time}")
            if next_scheduled_time > now:
                return False
