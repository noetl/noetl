from dataclasses import dataclass
from datetime import datetime
import uuid
from loguru import logger
from config import Config
from store import Store
from event import EventType
from task import Task
from step import Step


@dataclass
class Workflow:
    instance_id: str
    name: str
    start_date: datetime
    template: Config
    state: str
    store: Store
    initial_tasks: list[Task]

    @classmethod
    def create(cls, template: Config, store: Store):
        return cls(
            instance_id=f"{template.get_value('metadata.name')}-{uuid.uuid4()}",
            name=template.get_value('metadata.name'),
            start_date=datetime.now(),
            template=template,
            state=template.get_value('spec.initialSettings.state'),
            store=store,
            initial_tasks=[]

        )

    def get_instance_id(self):
        return f"{self.instance_id}.{self.name}"

    async def publish_event(self, event_type, payload):
        if self.store:
            await self.store.publish_event(instance_id=self.get_instance_id(), event_type=event_type, payload=payload)

    async def initialize_steps(self, task_name, task_config):
        logger.info(task_config)
        return (
            Step(
                workflow_instance_id=self.instance_id,
                task_name=task_name,
                name=step_key,
                description=step_entry.get("description"),
                step_type=step_entry.get("type"),
                command=step_entry.get("command"),
                args=step_entry.get("args"),
                state="ready",
                store=self.store
            )
            for step_key, step_entry in task_config.get("steps").items()
        )

    async def initialize_tasks(self):
        task_configs = await self.template.get_async(
            path="spec.initialSettings.start",
            store=self.store,
            instance_id=self.instance_id
        )
        task_names = task_configs.split(",")
        logger.info(task_names)
        for task_name in task_names:
            task_config = await self.template.get_async(f"spec.tasks.{task_name}", self.store, self.instance_id)
            steps = await self.initialize_steps(task_name, task_config)
            steps = list(steps)
            for step in steps:
                logger.info(step.__str__())
            task = Task.create(
                task_name=task_name,
                steps=steps,
                workflow_instance_id=self.instance_id,
                store=self.store,
                state=await self.template.get_async("spec.initialSettings.state", self.store, self.instance_id)
            )
            self.initial_tasks.append(task)

    async def execute_tasks(self):
        for task in self.initial_tasks:
            await task.execute()

    async def run_workflow(self):
        _ = await self.publish_event(EventType.WORKFLOW_INITIALIZED, self.state)
        _ = await self.publish_event(EventType.WORKFLOW_TEMPLATE, self.template)
        await self.initialize_tasks()
        _ = await self.publish_event(EventType.WORKFLOW_STARTED, self.state)
        await self.execute_tasks()
        await self.store.reload_events(self.instance_id)
