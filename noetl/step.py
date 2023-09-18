import json
from dataclasses import dataclass
import asyncio
from event_store import EventStore, Event, EventType
from loguru import logger

@dataclass
class Step:
    def __init__(self,
                 workflow_instance_id: str,
                 task_name: str,
                 name: str,
                 description: str,
                 step_type: str,
                 command: str,
                 args: list[str],
                 status: str,
                 event_store: EventStore
                 ):
        self.workflow_instance_id = workflow_instance_id
        self.task_name = task_name
        self.name = name
        self.description = description
        self.step_type = step_type
        self.command = command
        self.args = args
        self.status = status
        self.event_store = event_store
        self.output = ""
        self.error = ""
        self.exit_code = None

    def __str__(self):
        return ", ".join(f"{key}: {value}" for key, value in vars(self).items())

    async def publish_event(self, event_type, payload):
        event_id = f"{self.workflow_instance_id}.{self.task_name}.{self.name}.{event_type.as_str()}"
        if self.event_store:
            event = Event(event_id, event_type.as_str(), payload)
            await self.event_store.publish(workflow_instance_id=self.workflow_instance_id, event=event)

    async def execute(self):
        self.status = "in progress"
        try:
            await self.publish_event(EventType.STEP_STARTED, self.status)
            logger.info(f"{EventType.STEP_STARTED.as_str()}, {self.status}")
            if self.step_type == "shell":
                result = await self.execute_shell()
                self.output, self.error, self.exit_code = result
                self.status = "completed" if self.exit_code == 0 else "failed"
                await self.publish_event(EventType.TASK_COMPLETED, self.status)
                await self.publish_event(EventType.STEP_OUTPUT, json.dumps({self.output, self.error, self.exit_code}))
            else:
                self.error = "Unsupported step_type"
                self.status = "failed"
                await self.publish_event(EventType.TASK_FAILED, json.dumps({self.output, self.error, self.exit_code}))
        except Exception as e:
            self.error = str(e)
            self.status = "failed"
            await self.publish_event(EventType.TASK_FAILED, self.error)

    async def execute_shell(self):
        process = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            text=True
        )
        stdout, stderr = await process.communicate()
        return stdout, stderr, process.returncode

    def as_dict(self):
        return {
            "name": self.name,
            "step_type": self.step_type,
            "command": self.command,
            "args": self.args,
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code
        }
