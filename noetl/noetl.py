import json
from dataclasses import dataclass
from datetime import datetime
import uuid
import asyncio
from loguru import logger
from config import Config
from event_store import EventStore, Event, EventType
from task import Task
from step import Step


@dataclass
class Workflow:
    instance_id: str
    name: str
    start_date: datetime
    template: Config
    state: str
    event_store: EventStore
    initial_tasks: list[Task]

    @classmethod
    def create(cls, template: Config, event_store: EventStore):
        return cls(
            instance_id=f"{template.get_value('metadata.name')}-{uuid.uuid4()}",
            name=template.get_value('metadata.name'),
            start_date=datetime.now(),
            template=template,
            state=template.get_value('spec.initialSettings.state'),
            event_store=event_store,
            initial_tasks=[]

        )

    async def publish_event(self, event_type, payload):
        event_id = f"{self.instance_id}.{event_type.as_str()}"
        if self.event_store:
            event = Event(event_id, event_type.as_str(), payload)
            await self.event_store.publish(workflow_instance_id=self.instance_id, event=event)

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
                status="ready",
                event_store=self.event_store
            )
            for step_key, step_entry in task_config.get("steps").items()
        )

    async def initialize_tasks(self):
        task_configs = await self.template.get_async("spec.initialSettings.start", self.event_store, self.instance_id)
        task_names = task_configs.split(",")
        logger.info(task_names)
        for task_name in task_names:
            task_config = await self.template.get_async(f"spec.tasks.{task_name}", self.event_store, self.instance_id)
            steps = await self.initialize_steps(task_name, task_config)
            steps = list(steps)
            for step in steps:
                logger.info(step.__str__())
            task = Task.create(
                task_name=task_name,
                steps=steps,
                workflow_instance_id=self.instance_id,
                event_store=self.event_store,
                status=await self.template.get_async("spec.initialSettings.state", self.event_store, self.instance_id)
            )
            self.initial_tasks.append(task)

    async def execute_tasks(self):
        for task in self.initial_tasks:
            await task.execute()

    async def run_workflow(self):
        await self.publish_event(EventType.WORKFLOW_INITIALIZED, self.state)
        await self.publish_event(EventType.WORKFLOW_TEMPLATE, self.template)
        await self.initialize_tasks()
        await self.publish_event(EventType.WORKFLOW_STARTED, self.state)
        await self.execute_tasks()


if __name__ == "__main__":
    workflow_template = Config.create()
    logger.info(json.dumps(workflow_template, indent=4))
    workflow_template.update_vars()
    workflow = Workflow.create(workflow_template, EventStore("event_store"))
    asyncio.run(workflow.run_workflow())
