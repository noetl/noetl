import json
import sys
from src.components import generate_instance_id, Kind, BaseRepr
from src.components.exceptions import KindException, MetadataException, WorkflowConfigException
from src.components.meta import Metadata
from loguru import logger
from src.components.config import Config
from src.components.spec import Spec
from src.api.storage import db


class Dispatcher(BaseRepr):
    def __init__(self, dispatcher_config: Config):
        try:
            self.config = dispatcher_config
            logger.debug(dispatcher_config)

            kind = dispatcher_config.get_value("kind").lower()
            if kind != Kind.DISPATCHER.value:
                raise KindException(f"Unknown kind {kind}")

            name = dispatcher_config.get_value("metadata.name")
            if name is None:
                raise MetadataException("Name is empty")

            # TODO This is a placeholder for version control
            version = dispatcher_config.get_value("metadata.version")
            if version is None:
                raise MetadataException("Version is empty")

            self.metadata = Metadata(
                name=name,
                kind=Kind.DISPATCHER,
                version=version,
                instance_id=generate_instance_id()
            )

            self.spec = Spec(spec=Config(dispatcher_config.get_value("spec")))

            self.dispatcher_key = f"dispatcher:{self.metadata.name}"
            self.dispatcher_instance_id_key = f"{self.dispatcher_key}:{self.metadata.instance_id}"
            self.print()

        except Exception as e:
            logger.error(f"Setting up a dispatcher failed {e}")
            sys.exit(1)

    @classmethod
    async def create(cls, config: Config):
        dispatcher_config = await Config.create(config.config_path)
        return cls(dispatcher_config)

    async def save_instance_id(self):
        try:
            instance_id_key = f"{self.dispatcher_key}:instance-id"
            await db.save(instance_id_key, self.metadata.instance_id)
            logger.info(
                f"Dispatcher InstanceId {self.metadata.instance_id} saved under {instance_id_key} key")
        except Exception as e:
            logger.error(e)

    async def save_dispatcher(self):
        await self.save_instance_id()
        dispatcher_config_key = f"dispatcher:{self.metadata.name}:{self.metadata.version}:config"
        try:
            await db.save(dispatcher_config_key, json.dumps(self.config))
        except Exception as e:
            logger.error(e)
        logger.debug(await self.get_dispatcher(dispatcher_config_key))

    @staticmethod
    async def get_dispatcher(config_key: str):
        try:
            logger.debug(f"retrieve key {config_key}")
            value = await db.load(config_key)
            logger.debug(f"retrieve key {config_key} value {value}")
            return value
        except Exception as e:
            logger.error(e)

    async def process_workflow_configs(self):
        dispatcher_config = Config(
            json.loads(
                await self.get_dispatcher(f"dispatcher:{self.metadata.name}:{self.metadata.version}:config")
            )
        )
        logger.info(dispatcher_config)
        for workflow_path in dispatcher_config.get_value("spec.workflowConfigPaths"):
            logger.info(workflow_path)
            await self.save_workflow_config(config_path=workflow_path.get("configPath"))

    async def save_workflow_config(self, config_path):
        try:
            workflow_config = await Config.create(config_path)
            name = workflow_config.get_value("metadata.name")
            if name is None:
                raise WorkflowConfigException(f"Metadata name is missing in workflow config.")
            await db.save(f"{self.dispatcher_instance_id_key}:workflow:{name}:config", json.dumps(workflow_config))
        except Exception as e:
            logger.error(f"Saving workflow templates failed {e}")
            sys.exit(1)

    async def run_workflows(self):

        workflow_config_keys = await db.get_keys(f"{self.dispatcher_instance_id_key}:workflow:*")
        logger.debug(workflow_config_keys)
        for key in workflow_config_keys:
            split_key = key.split(':')
            workflow_name_index = split_key.index('workflow')
            name = split_key[workflow_name_index + 1]
            logger.debug(name)
