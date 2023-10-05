from enum import Enum
from dataclasses import dataclass
from datetime import datetime
import base64
import re
import json

class EventType(Enum):
    WORKFLOW_INITIALIZED = "workflow_initialized"
    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_TEMPLATE = "workflow_template"
    WORKFLOW_STATE = "workflow_state"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_OUTPUT = "task_output"
    TASK_STATE = "task_state"
    STEP_STARTED = "step_started"
    STEP_COMPLETED = "step_completed"
    STEP_FAILED = "step_failed"
    STEP_OUTPUT = "step_output"
    step_state="step_state"

    def as_str(self):
        return self.value


@dataclass
class Event:
    event_id: str
    event_type: EventType
    metadata: dict | None
    payload: any
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()

    def as_dict(self):
        return {
            "eventId": self.event_id,
            "eventType": self.event_type.as_str(),
            "metadata": self.metadata,
            "payload": self.serialize_payload(),
            "timestamp": self.timestamp
        }

    def get_workflow_id(self):
        match = re.match(r'^[^.]*', self.event_id)
        return match.group() if match else self.event_id

    @classmethod
    def create(cls, event_id, event_type, payload, metadata: dict = None):
        event_id = event_id
        event_type = event_type
        metadata = (metadata if metadata else {}) | {"payload_data_type": type(payload).__name__}
        payload = payload
        return cls(event_id, event_type, metadata, payload)

    def serialize_payload(self):
        return  base64.b64encode(json.dumps(self.payload).encode()).decode()

    @classmethod
    def from_dict(cls, event):
        event_id = event.get("eventId")
        event_type = event.get("eventType")
        payload = cls.deserialize_payload(event.get("payload"))
        metadata = event.get("metadata")
        timestamp = event.get("timestamp")
        return cls(event_id, event_type, metadata, payload, timestamp)

    @staticmethod
    def deserialize_payload(payload_data):
        return base64.b64decode(payload_data).decode()
