import os
import json
from enum import Enum
import aiofiles
from dataclasses import dataclass
from datetime import datetime
import threading


class EventType(Enum):
    WORKFLOW_INITIALIZED = "workflow_initialized"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_TEMPLATE = "workflow_template"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_OUTPUT = "task_output"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_OUTPUT = "step_output"

    def as_str(self):
        return self.value


@dataclass
class Event:
    event_id: str
    event_type: str
    payload: dict
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def as_dict(self):
        return {
            "eventId": self.event_id,
            "eventType": self.event_type,
            "payload": self.payload,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            event_id=data["eventId"],
            event_type=data["eventType"],
            payload=data["payload"],
            timestamp=data["timestamp"]
        )


class EventStore:
    def __init__(self, data_dir: str = "noetldb"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.in_memory_store = {}
        self.lock = threading.Lock()

    async def file_save(self, workflow_instance_id: str, event: Event):
        file_path = os.path.join(self.data_dir, f"{workflow_instance_id}_events.json")
        async with aiofiles.open(file_path, 'a') as file:
            await file.write(json.dumps(event.as_dict()) + '\n')

    async def publish(self, workflow_instance_id: str, event: Event):
        with self.lock:
            await self.file_save(workflow_instance_id, event)
            if event.event_id not in self.in_memory_store:
                self.in_memory_store[event.event_id] = event

    async def lookup(self, event_id: str):
        with self.lock:
            return self.in_memory_store.get(event_id, None)

    async def reload_events(self, workflow_instance_id: str):
        file_path = os.path.join(self.data_dir, f"{workflow_instance_id}_events.json")
        events = []
        async with aiofiles.open(file_path, 'r') as file:
            async for line in file:
                event = Event.from_dict(json.loads(line))
                if event is not None:
                    with self.lock:
                        self.in_memory_store[event.event_id] = event
