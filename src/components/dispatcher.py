import json
import sys
from src.components import generate_instance_id, Kind, BaseRepr
from src.components.models import KindException, MetadataException, SpecException, WorkflowConfigException
from src.components.models.meta import Metadata
from loguru import logger
from src.components.models.config import Config, DictTemplate
from src.components.models.spec import DispatcherSpec, DispatcherSpecWorkflow
from src.storage import db


class Dispatcher(BaseRepr):
    def __init__(self, dispatcher_config: DictTemplate):
        try:
            self.template = dispatcher_config
            logger.debug(self.template)

            kind = self.template.get_value("kind").lower()
            if kind != Kind.DISPATCHER.value:
                raise KindException(f"Unknown kind {kind}")

            name = self.template.get_value("metadata.name")
            if name is None:
                raise MetadataException("Name is empty")

            self.metadata = Metadata(
                name=name,
                kind=Kind.DISPATCHER
            )

            self.spec = DispatcherSpec(instance_id=generate_instance_id(name))

            if self.template.get_value("spec.workflows") is None:
                raise SpecException(f"Spec workflows are missing")

            self.add_spec_workflows()
            self.key_instance = f"/dispatcher/{self.metadata.name}"
            self.key_instance_id = f"{self.key_instance}/{self.spec.instance_id}"
            self.print()

        except Exception as e:
            logger.error(f"Setting up a dispatcher failed {e}")
            sys.exit(1)

    @classmethod
    async def create(cls, config: Config):
        dispatcher_config = await DictTemplate.create(config.config_path)
        return cls(dispatcher_config)

    def add_spec_workflows(self):
        for config_path in self.template.get_value("spec.workflows"):
            self.spec.workflows.append(DispatcherSpecWorkflow(config_path=config_path))

    async def save_instance_id(self):
        await db.save(f"{self.key_instance}/instance-id", self.spec.instance_id)
        logger.info(f"Dispatcher instance ID {self.spec.instance_id} saved under {self.key_instance}/instance-id key")

    async def save_dispatcher_template(self):
        await self.save_instance_id()
        await db.save(f"{self.key_instance_id}/template", json.dumps(self.template))
        logger.debug(await self.get_dispatcher_template())

    async def get_dispatcher_template(self):
        return await db.load(f"{self.key_instance_id}/template")

    async def process_workflow_configs(self):
        template = DictTemplate(json.loads(await self.get_dispatcher_template()))
        logger.info(template)
        for workflow_path in template.get_value("spec.workflows"):
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
