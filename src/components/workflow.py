from loguru import logger
from datetime import datetime

from src.components import generate_instance_id
from src.components.fsm import FiniteAutomata
from src.components.config import Metadata, Spec, Kind, Config, KindTemplate
from src.components.job import Job
from src.components.config import Config
from src.storage import read_yaml
from src.components.template import get_object_value
from src.storage.redis_storage import RedisStorage
from typing import Optional, Union, Any


class Workflow(FiniteAutomata):
    """
    A Workflow class that represents a single workflow instance and inherits from the FiniteAutomata class.
    :param config: The configuration object containing the workflow configuration path.
    :type config: Config
    :param workflow_config: A dictionary containing the parsed workflow configuration.
    :type workflow_config: dict
    """

    def __init__(self, workflow_config: KindTemplate, config: Config):
        """
        Initializes a new Workflow instance based on the provided configuration.
        :param config: The configuration object containing the workflow configuration path.
        :type config: Config
        :param workflow_config: A dictionary containing the parsed workflow configuration.
        :type workflow_config: dict
        """

        try:
            if workflow_config.get_value("kind").lower() == Kind.WORKFLOW.value:
                metadata = Metadata(
                            name=workflow_config.get_value("metadata.name"),
                            kind=Kind.WORKFLOW
                        )
                spec = Spec()
                spec.schedule = workflow_config.get_value("spec.schedule")
                spec.variables = workflow_config.get_value("spec.variables")
                spec.state = workflow_config.get_value("spec.initialState")
                spec.transitions = workflow_config.get_value("spec.transitions")
                spec.conditions = workflow_config.get_value("spec.conditions")
                spec.instance_id = generate_instance_id(metadata.name)
                super().__init__(
                    metadata=metadata,
                    spec=spec,
                    config=config
                )
            # self.spec = workflow_config.get_value("spec")
            #self.db: Optional[Union[RedisStorage]] = RedisStorage(config.redis_config)

            #self.print()
        except Exception as e:
            logger.error(f"Setting up a dispatcher template failed {e}")


        #
        # self.workflow_template: dict = workflow_config
        # self.jobs: list = []
        # self.define_jobs(jobs_config=get_object_value(workflow_config, "spec.jobs"))

    @classmethod
    async def create(cls, config: Config ):
        workflow_config = await KindTemplate.create(config.config_path)
        return cls(workflow_config, config)

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
            workflow_template = await read_yaml(config.config_path)
            logger.info(workflow_template)
            workflow = Workflow(
                config=config, workflow_config=workflow_template
            )
            if workflow:
                await workflow.set_storage()
                await workflow.spec.db.pool_connect()
                return workflow
            return

        except Exception as e:
            logger.error(f"Setting up a workflow template failed {e}")

    @staticmethod
    def generate_workflow_instance_id(name: str) -> str:
        """
        Generate a unique workflow instance ID based on the workflow name and the current timestamp.
        The generated ID will have the format "name-YYYYmmddTHHMMSSZ". That the IDs are
        naturally ordered when sorted lexicographically.
        :param name: The name of the workflow.
        :type name: str
        """
        now = datetime.utcnow()
        timestamp = now.strftime("%Y%m%dT%H%M%SZ")
        instance_id =f"{name}-{timestamp}"
        logger.info(instance_id)
        return instance_id

    def define_jobs(self, jobs_config):
        """
        Defines jobs for the Workflow instance based on the provided workflow_jobs_config.
        Args:
            workflow_jobs_config: The configuration for the jobs.
        """
        logger.info(jobs_config)
        for job_config in jobs_config:
            job = Job(
                workflow_name=self.metadata.name,
                workflow_spec=self.spec,
                job_config=job_config
            )
            self.jobs.append(job)

    async def execute(self):
        """
        Executes the Workflow instance by running its jobs in the order they were defined.
        Sets the Workflow state to RUNNING and logs the execution process.
        """
        self.set_state("running")
        logger.info(f"Executing workflow {self.metadata.name}")
        for job in self.jobs:
            await job.execute()
