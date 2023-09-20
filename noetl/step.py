import json
from dataclasses import dataclass
import asyncio
from store import Store
from event import EventType
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
                 state: str,
                 store: Store
                 ):
        self.workflow_instance_id = workflow_instance_id
        self.task_name = task_name
        self.name = name
        self.description = description
        self.step_type = step_type
        self.command = command
        self.args = args
        self.state = state
        self.store = store
        self.output = ""
        self.error = ""
        self.exit_code = ""

    def __str__(self):
        return ", ".join(f"{key}: {value}" for key, value in vars(self).items())

    def get_instance_id(self):
        return f"{self.workflow_instance_id}.{self.task_name}.{self.name}"

    async def publish_event(self, event_type, payload):
        if self.store:
            await self.store.publish_event(instance_id=self.get_instance_id(), event_type=event_type, payload=payload)

    async def execute(self):
        self.status = "in progress"
        try:
            _ = await self.publish_event(EventType.STEP_STARTED, payload=self.status)
            if self.step_type == "shell":
                result = await self.execute_shell()
                self.output, self.error, self.exit_code = result
                self.status = "completed" if self.exit_code == 0 else "failed"
                _ = await self.publish_event(EventType.TASK_COMPLETED, payload=self.status)
                _ = await self.publish_event(EventType.STEP_OUTPUT, payload={self.output, self.error, self.exit_code})
            else:
                self.error = "Unsupported step_type"
                self.status = "failed"
                _ = await self.publish_event(EventType.TASK_FAILED, payload={self.output, self.error, self.exit_code})
        except Exception as e:
            self.error = str(e)
            self.status = "failed"
            _ = await self.publish_event(EventType.TASK_FAILED, payload=self.error)

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
        self_dict = {
            "name": self.name,
            "step_type": self.step_type,
            "command": self.command,
            "args": self.args,
            "state": self.state,
            "output": self.output,
            "error": self.error,
            "exit_code": self.exit_code
        }
        logger.debug(self_dict)
        return self_dict
