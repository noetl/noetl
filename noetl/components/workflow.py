from loguru import logger
from noetl.components import Kind
from noetl.components.exceptions import KindException, MetadataException
from noetl.components.fsm import FiniteAutomata
from noetl.components.meta import Metadata
from noetl.components.spec import Spec
from src.api.config import Config


class Workflow(FiniteAutomata):

    def __init__(self, workflow_config: Config):

        try:
            kind = workflow_config.get_value("kind").lower()
            if kind != Kind.WORKFLOW.value:
                raise KindException(f"Unknown kind {kind}")

            name = workflow_config.get_value("metadata.name")
            if name is None:
                raise MetadataException("Name is empty")

            spec = Spec(spec=Config(workflow_config.get_value("spec")))

            super().__init__(
                initial_state=spec.initial_state,
                transitions=spec.transitions,
                conditions=spec.conditions if spec.conditions is not None else None
            )

            self.metadata = Metadata(
                name=name,
                kind=Kind.WORKFLOW
            )

            self.spec = spec

        except Exception as e:
            logger.error(f"Setting up a dispatcher template failed {e}")

    @classmethod
    async def create(cls, config: Config):
        workflow_config = await Config.create(config.config_path)
        return cls(workflow_config)

    # @staticmethod
    # async def initialize_workflow(config: Config):
    #     """
    #     Asynchronously initializes a new workflow instance based on the provided configuration.
    #     :param config: The configuration object containing the single workflow configuration.
    #     :type config: Config
    #     :return: An initialized Workflow instance with connected storage.
    #     :rtype: Workflow
    #     :raises Exception: If there is an error during the initialization process.
    #     """
    #     try:
    #         workflow_template = await read_yaml(config.config_path)
    #         logger.info(workflow_template)
    #         workflow = Workflow(
    #             config=config, workflow_config=workflow_template
    #         )
    #         if workflow:
    #             await workflow.set_storage()
    #             await workflow.spec.db.pool_connect()
    #             return workflow
    #         return
    #
    #     except Exception as e:
    #         logger.error(f"Setting up a workflow template failed {e}")
    #
    # def define_jobs(self, jobs_config):
    #     """
    #     Defines jobs for the Workflow instance based on the provided workflow_jobs_config.
    #     Args:
    #         workflow_jobs_config: The configuration for the jobs.
    #     """
    #     logger.info(jobs_config)
    #     for job_config in jobs_config:
    #         job = Job(
    #             workflow_name=self.metadata.name,
    #             workflow_spec=self.spec,
    #             job_config=job_config
    #         )
    #         self.jobs.append(job)
    #
    #
    #
