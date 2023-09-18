from dataclasses import dataclass
from event_store import EventStore, Event, EventType
from step import Step
from loguru import logger

@dataclass
class Task:
    def __init__(self,
                 workflow_instance_id: str,
                 name: str,
                 steps: list[Step],
                 status: str,
                 event_store: EventStore
                 ):
        self.workflow_instance_id = workflow_instance_id
        self.name = name
        self.workflow_instance_id = workflow_instance_id
        self.steps = steps
        self.status = status
        self.event_store = event_store

    @classmethod
    def create(cls,
               task_name: str,
               steps,
               status,
               workflow_instance_id: str,
               event_store: EventStore
               ):
        return cls(name=task_name,
                   steps=steps,
                   workflow_instance_id=workflow_instance_id,
                   event_store=event_store,
                   status=status
                   )

    async def publish_event(self, event_type, payload):
        event_id = f"{self.workflow_instance_id}.{self.name}.{event_type.as_str()}"
        if self.event_store:
            event = Event(event_id, event_type.as_str(), payload)
            await self.event_store.publish(workflow_instance_id=self.workflow_instance_id, event=event)

    async def execute(self):
        self.status = "in progress"
        await self.publish_event(EventType.TASK_STARTED, self.status)
        logger.info(f"{EventType.TASK_STARTED.as_str()}, {self.status}")
        logger.info(f"{self.steps}")
        for step in self.steps:
            logger.info(step)
            await step.execute()
        self.status = "completed" if all(step.status == "completed" for step in self.steps) else "failed"
        await self.publish_event(EventType.TASK_COMPLETED if self.status == "completed" else EventType.TASK_FAILED,
                                 self.status)

    def as_dict(self):
        return {
            "name": self.name,
            "steps": [step.as_dict() for step in self.steps],
            "status": self.status
        }
