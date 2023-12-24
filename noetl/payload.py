import uuid
from datetime import datetime
from enum import Enum
from keyval import KeyVal
from natstream import NatsPool, NatsConnectionPool, NatsConfig, ErrTimeout, PubAck


class PayloadType(Enum):
    """
    Enum class representing payload type.

    Attributes:
        EVENT (str): Payload type for events.
        COMMAND (str): Payload type for commands.
    """
    EVENT = "event"
    COMMAND = "command"


class PayloadIdentifier:
    def __init__(self,
                 timestamp=None,
                 current_id=None,
                 origin_id=None,
                 previous_id=None):
        self.timestamp: str = timestamp if timestamp else str(int(datetime.now().timestamp() * 1000))
        self.current_id: str = current_id if current_id else str(uuid.uuid4())
        self.previous_id: str = previous_id if previous_id else self.current_id
        self.origin_id: str = origin_id if origin_id else self.current_id

    def get_identifier(self):
        return {
            "timestamp": self.timestamp,
            "current_id": self.current_id,
            "previous_id": self.previous_id,
            "origin_id": self.origin_id
        }

    def get_api_identifier(self) -> str:
        return f"{self.origin_id}.{self.previous_id}.{self.current_id}"


class PayloadReference:

    def __init__(self,
                 subject: str = None,
                 previous_id: str = None,
                 origin_id: str = None,
                 stream: str = None,
                 seq: str = None,
                 playbook: dict = None,
                 task: dict = None,
                 step: dict = None):
        identifier = PayloadIdentifier(previous_id=previous_id,
                                            origin_id=origin_id) if previous_id else PayloadIdentifier()
        self.subject = subject,
        self.identifier: PayloadIdentifier =identifier
        self.stream = stream,
        self.seq = seq,
        self.playbook = playbook,
        self.task = task,
        self.step = step

    def get_reference(self):
        return {
            "identifier": self.identifier.get_identifier(),
            "subject": self.subject,
            "stream": self.stream,
            "seq": self.seq,
            "playbook": self.playbook,
            "task": self.task,
            "step": self.step
        }

    def get_api_reference(self):
        return {
            "identifier": self.identifier.get_api_identifier(),
            "subject": self.subject,
            "stream": self.stream,
            "seq": self.seq,
            "playbook": self.playbook,
            "task": self.task,
            "step": self.step
        }


class Payload(KeyVal, NatsPool):
    """A class representing a payload.

    The Payload class is used for handling payloads. It inherits from the KeyVal and NatsPool classes.

    Args:
        *args: Variable length argument list.
        nats_pool (NatsConnectionPool | NatsConfig, optional): An instance of NatsConnectionPool or NatsConfig class.
        **kwargs: Arbitrary keyword arguments.
    """

    def __init__(self, *args, nats_pool: NatsConnectionPool | NatsConfig = None, **kwargs):
        super().__init__(*args, **kwargs)
        if nats_pool:
            self.initialize_nats_pool(nats_pool)

    def set_reference(self, reference: PayloadReference):
        self.set_value("metadata.reference", reference.get_reference())

    def get_subject(self):
        return self.get_value("metadata.reference.subject")

    def get_origin_id(self):
        return self.get_value("metadata.reference.identifier.origin_id")

    def get_reference(self):
        return self.get_value("metadata.reference")

    def set_event_type(self, event_type):
        self.set_value("metadata.event_type", event_type)

    def set_command_type(self, command_type):
        self.set_value("metadata.command_type", command_type)

    @classmethod
    def create(cls,
               payload_data,
               nats_pool: NatsConnectionPool | NatsConfig = None,
               subject=None,
               origin_id=None,
               current_id=None,
               event_type=None,
               command_type=None
               ):
        payload_reference = PayloadReference(subject=subject, origin_id=origin_id, previous_id=current_id)
        payload = cls(payload_data, nats_pool=nats_pool)
        payload.set_reference(reference=payload_reference)
        if event_type:
            payload.set_event_type(event_type)
        if command_type:
            payload.set_command_type(command_type)
        return payload

    @classmethod
    def kv(cls, payload_data, nats_pool: NatsConnectionPool | NatsConfig = None):
        return cls(payload_data, nats_pool=nats_pool)
