import json

from src.components import BaseRepr, generate_instance_id
from src.components.fsm import Metadata
# /dispatcher-name/workflows/worfklow-name/workflow-instance-id/jobs/job-name/tasks/task-name/actions/action-name=action-state (json structure)
from loguru import logger
from src.components.config import Config, Kind, KindTemplate
from src.storage.redis_storage import RedisStorage
from typing import Optional, Union, Any
from src.components.workflow import Workflow


class Dispatcher(BaseRepr):
    def __init__(self, dispatcher_config: KindTemplate, config: Config):
        try:
            if dispatcher_config.get_value("kind").lower() == Kind.DISPATCHER.value:
                name = dispatcher_config.get_value("metadata.name")
                self.metadata = Metadata(
                    name=name,
                    kind=Kind.DISPATCHER
                )
                self.spec = dispatcher_config.get_value("spec")
                self.instance_id = generate_instance_id(name)
                self.template = dispatcher_config
                self.db: Optional[Union[RedisStorage]] = RedisStorage(config.redis_config)
                self.workflows: list = []

            self.print()
        except Exception as e:
            logger.error(f"Setting up a dispatcher template failed {e}")

    @classmethod
    async def create(cls, config: Config):
        dispatcher_config = await KindTemplate.create(config.config_path)
        return cls(dispatcher_config, config)

    async def save_instance_id(self):
        await self.db.save(f"/{self.metadata.name}/instance-id", self.instance_id)

    async def save_dispatcher_template(self):
        logger.info(self.template)
        await self.db.save(f"/{self.metadata.name}/{self.instance_id}/template", json.dumps(self.template))

    async def get_dispatcher_template(self):
        return await self.db.load(f"/{self.metadata.name}/{self.instance_id}/template")

    async def create_workflows(self):
        template = json.loads(await self.get_dispatcher_template()).get("spec")
        logger.info(template)
        for dispatcher_spec in template.get("workflows"):
            logger.info(dispatcher_spec)
            config=Config(config_path=dispatcher_spec.get("config"))
            logger.info(config)
            workflow = await Workflow.create(config=config)
            self.workflows.append(workflow)

        # workflow = await Workflow.create(config=Config(config_path=args.config))

#     async def run(self):
#         tasks = [self.trigger_workflow(workflow) for workflow in self.config['spec']['workflows']]
#         await asyncio.gather(*tasks)
#
#     async def trigger_workflow(self, workflow):
#         print(f"Triggering workflow {workflow['name']} from {workflow['path']}")
#
#         # Load the workflow configuration
#         with open(workflow['path'], 'r') as file:
#             workflow_config = yaml.safe_load(file)
#
#         # Generate a unique instance id for the workflow
#         instance_id = uuid.uuid4().hex
#
#         # Register the workflow and its configuration in Redis
#         await self.storage.set(f"{self.config['metadata']['name']}/workflows/{workflow['name']}/{instance_id}", yaml.dump(workflow_config))
#
#         # Start a new instance of the application with the workflow instance id
#         subprocess.Popen(["python", "src/main.py", instance_id])
#
#         # Wait a while before checking state
#         await asyncio.sleep(5)
#
#         # Check the state of the workflow in Redis
#         state = await self.storage.get(f"{self.config['metadata']['name']}/workflows/{workflow['name']}/{instance_id}")
#         print(f"Workflow {workflow['name']} is {state}")
#
# # Create a dispatcher with the configuration file
# dispatcher = Dispatcher('path/to/dispatcher.yaml')

# Run the dispatcher, which triggers the workflows
# asyncio.run(dispatcher.run())
