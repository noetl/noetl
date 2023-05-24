from loguru import logger
from datetime import datetime
from croniter import croniter
from src.components.fsm import FiniteAutomata
from src.components.config import  Metadata, Spec, Kind
from src.components.task import Task
from src.components.template import get_object_value


class Job(FiniteAutomata):
    """
    A Job class that represents a single job instance within a Workflow and inherits from the FiniteAutomata class.

    Args:
        workflow_name (str): The name of the parent Workflow.
        workflow_spec (Spec): The specification of the parent Workflow.
        job_config (dict): A dictionary containing the parsed job configuration.
    """

    def __init__(self, workflow_name: str, workflow_spec: Spec, job_config: dict):
        """
        Initializes a new Job instance based on the provided configuration.

        Args:
            workflow_name (str): The name of the parent Workflow.
            workflow_spec (Spec): The specification of the parent Workflow.
            job_config (dict): A dictionary containing the parsed job configuration.
        """

        metadata = Metadata(
            name=get_object_value(job_config, "name"),
            kind=Kind.JOB)
        spec = Spec()
        spec.runtime = get_object_value(job_config, "runtime")
        spec.state = workflow_spec.state
        spec.transitions = workflow_spec.transitions
        spec.conditions = get_object_value(job_config, "conditions")
        spec.instance_id = workflow_spec.instance_id
        spec.db = workflow_spec.db
        super().__init__(
            metadata=metadata,
            spec=spec
        )

        self.workflow_name: str = workflow_name
        self.tasks = []
        self.define_tasks(tasks_config=job_config.get("tasks"))

    def define_tasks(self, tasks_config):
        """
        Defines tasks for the Job instance based on the provided job_config.

        Args:
            tasks_config: The configuration for the tasks.
        """
        for task_config in tasks_config:
            task = Task(
                workflow_name=self.workflow_name,
                job_name=self.metadata.name,
                job_spec=self.spec,
                task_config=task_config
            )
            self.tasks.append(task)

    async def execute(self):
        """
        Executes the Job instance by running its tasks in the order they were defined.
        Sets the Job state to "running" and logs the execution process.
        """
        self.set_state("running")
        logger.info(f"Executing job {self.metadata.name}")
        for task in self.tasks:
            await task.execute()

    def job_ready(self) -> bool:
        """
        Determines if the Job is ready to be executed based on its state and schedule.

        Returns:
            bool: True if the Job is ready to be executed, False otherwise.
        """
        if self.state == "ready":
            return False

        if self.spec.schedule:
            now = datetime.now()
            iter = croniter(self.spec.schedule, now)
            next_scheduled_time = iter.get_next(datetime)
            logger.info(f"Next scheduled time {next_scheduled_time}")
            if next_scheduled_time > now:
                return False
