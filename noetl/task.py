from dataclasses import dataclass
from store import Store
from event import EventType
from step import Step
from loguru import logger

@dataclass
class Task:
    def __init__(self,
                 workflow_instance_id: str,
                 name: str,
                 steps: list[Step],
                 state: str,
                 store: Store
                 ):
        self.workflow_instance_id = workflow_instance_id
        self.name = name
        self.workflow_instance_id = workflow_instance_id
        self.steps = steps
        self.state = state
        self.store = store

    @classmethod
    def create(cls,
               task_name: str,
               steps,
               state,
               workflow_instance_id: str,
               store: Store
               ):
        return cls(name=task_name,
                   steps=steps,
                   workflow_instance_id=workflow_instance_id,
                   store=store,
                   state=state
                   )

    def get_instance_id(self):
        return f"{self.workflow_instance_id}.{self.name}"

    async def publish_event(self, event_type, payload):
        if self.store:
            _ = await self.store.publish_event(instance_id=self.get_instance_id(), event_type=event_type, payload=payload)

    async def execute(self):
        self.state = "in progress"
        _ = await self.publish_event(EventType.TASK_STARTED, self.state)
        for step in self.steps:
            logger.info(step)
            await step.execute()
        self.state = "completed" if all(step.status == "completed" for step in self.steps) else "failed"
        _ = await self.publish_event(EventType.TASK_COMPLETED if self.state == "completed" else EventType.TASK_FAILED,
                                 self.state)

    def as_dict(self):
        return {
            "name": self.name,
            "steps": [step.as_dict() for step in self.steps],
            "status": self.state
        }
