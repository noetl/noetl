import json
import sys
from src.components import generate_instance_id, Kind, BaseRepr
from src.components.models import KindException, MetadataException, SpecException, WorkflowConfigException
from src.components.models.meta import Metadata
from loguru import logger
from src.components.models.config import Config, DictTemplate
from src.components.models.spec import Spec
from src.storage import db


class Dispatcher(BaseRepr):
    def __init__(self, dispatcher_config: DictTemplate):
        try:
            self.template = dispatcher_config
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

            self.spec = Spec(spec=DictTemplate(dispatcher_config.get_value("spec")))

            self.key_instance = f"dispatcher:{self.metadata.name}"
            self.key_instance_id = f"{self.key_instance}:{self.metadata.instance_id}"
            self.print()

        except Exception as e:
            logger.error(f"Setting up a dispatcher failed {e}")
            sys.exit(1)

    @classmethod
    async def create(cls, config: Config):
        dispatcher_config = await DictTemplate.create(config.config_path)
        return cls(dispatcher_config)

    async def save_instance_id(self):
        try:
            await db.save(f"{self.key_instance}:instance-id", self.metadata.instance_id)
            logger.info(
                f"Dispatcher instance ID {self.metadata.instance_id} saved under {self.key_instance}:instance-id key")
        except Exception as e:
            logger.error(e)

    async def save_dispatcher_template(self):
        await self.save_instance_id()
        try:
            await db.save(f"template:dispatcher:{self.metadata.name}:{self.metadata.version}", json.dumps(self.template))
        except Exception as e:
            logger.error(e)
        logger.debug(await self.get_dispatcher_template(f"template:dispatcher:{self.metadata.name}:{self.metadata.version}"))

    @staticmethod
    async def get_dispatcher_template(template_key: str):
        return await db.load(template_key)

    async def process_workflow_configs(self):
        template = DictTemplate(
            json.loads(
                await self.get_dispatcher_template(f"template:dispatcher:{self.metadata.name}:{self.metadata.version}")
            )
        )
        logger.info(template)
        for workflow_path in template.get_value("spec.workflowConfigPaths"):
            logger.info(workflow_path)
            await self.save_workflow_template(config_path=workflow_path.get("configPath"))

    async def save_workflow_template(self, config_path):
        try:
            workflow_config = await DictTemplate.create(config_path)
            name = workflow_config.get_value("metadata.name")
            if name is None:
                raise WorkflowConfigException(f"Metadata name is missing in workflow config.")
            await db.save(f"{self.key_instance_id}/workflows/{name}/template", json.dumps(workflow_config))
        except Exception as e:
            logger.error(f"Saving workflow templates failed {e}")
            sys.exit(1)
