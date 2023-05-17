from typing import Optional
from loguru import logger
from datetime import datetime
from workflow_engine.src.components.finite_automata import FiniteAutomata
from workflow_engine.src.components.job import Job
from workflow_engine.src.components.config import Config
from workflow_engine.src.storage import read_yaml
from workflow_engine.src.components.template import get_object_value


class Workflow(FiniteAutomata):
    """
    A Workflow class that represents a single workflow instance and inherits from the FiniteAutomata class.
    :param config: The configuration object containing the workflow configuration path.
    :type config: Config
    :param workflow_config: A dictionary containing the parsed workflow configuration.
    :type workflow_config: dict
    """

    def __init__(self, config: Config, workflow_config: dict):
        """
        Initializes a new Workflow instance based on the provided configuration.
        :param config: The configuration object containing the workflow configuration path.
        :type config: Config
        :param workflow_config: A dictionary containing the parsed workflow configuration.
        :type workflow_config: dict
        """
        super().__init__(config=config,
                         name=get_object_value(workflow_config, "metadata.name"),
                         conditions=get_object_value(workflow_config, "spec.conditions")
                         )
        self.jobs: list = []
        self.schedule: Optional[str] = get_object_value(workflow_config, "spec.schedule")
        self.variables: Optional[dict] = get_object_value(workflow_config, "spec.variables")
        self.generate_workflow_instance_id(get_object_value(workflow_config,"metadata.name"))
        self.define_jobs(workflow_jobs_config=get_object_value(workflow_config, "spec.jobs"))

    @staticmethod
    async def initialize_workflow(config: Config):
        """
        Asynchronously initializes a new workflow instance based on the provided configuration.
        :param config: The configuration object containing the single workflow configuration.
        :type config: Config
        :return: An initialized Workflow instance with connected storage.
        :rtype: Workflow
        :raises Exception: If there is an error during the initialization process.
        """
        try:
            workflow_template = await read_yaml(config.workflow_config_path)
            logger.info(workflow_template)
            workflow = Workflow(
                config=config, workflow_config=workflow_template
            )
            if workflow:
                await workflow.set_storage()
                await workflow.db.pool_connect()
                return workflow
            return

        except Exception as e:
            logger.error(f"Setting up a workflow template failed {e}")

    def generate_workflow_instance_id(self, name: str):
        """
        Generate a unique workflow instance ID based on the workflow name and the current timestamp.
        The generated ID will have the format "name-YYYYmmddTHHMMSSZ". That the IDs are
        naturally ordered when sorted lexicographically.
        :param name: The name of the workflow.
        :type name: str
        """
        now = datetime.utcnow()
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        self.instance_id = f"{name}-{timestamp}"

    def define_jobs(self, workflow_jobs_config):
        """
        Defines jobs for the Workflow instance based on the provided workflow_jobs_config.
        Args:
            workflow_jobs_config: The configuration for the jobs.
        """
        logger.info(workflow_jobs_config)
        for job_config in workflow_jobs_config:
            job = Job(
                workflow_name=self.name,
                instance_id=self.instance_id,
                job_config=job_config
            )
            self.jobs.append(job)

    async def execute(self):
        """
        Executes the Workflow instance by running its jobs in the order they were defined.
        Sets the Workflow state to RUNNING and logs the execution process.
        """
        self.set_state("running")
        logger.info(f"Executing workflow {self.name}")
        for job in self.jobs:
            await job.execute()
