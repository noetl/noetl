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

    def set_reference(self, timestamp=None, subject=None, origin_id=None, previous_id=None,
                      stream=None, seq=None, context=None):
        if subject:
            self.set_value("metadata.reference.subject", subject)
        self.set_value("metadata.reference.timestamp",
                       timestamp if timestamp else str(int(datetime.now().timestamp() * 1000)))
        self.set_value("metadata.reference.current_id",str(uuid.uuid4()))
        self.set_value("metadata.reference.previous_id",
                       previous_id if previous_id else self.get_value("metadata.reference.current_id"))
        self.set_value("metadata.reference.origin_id",
                       origin_id if origin_id else self.get_value("metadata.reference.current_id"))
        if stream:
            self.set_value("metadata.reference.stream", stream)
        if seq:
            self.set_value("metadata.reference.seq", seq)
        if context:
            self.set_value("metadata.reference.context", context)

    def get_reference(self):
        return self.get_keyval("metadata.reference")

    def get_payload_reference(self):
        return self.get_identifier() | {
            "subject": self.get_subject(),
            "stream": self.get_stream(),
            "seq": self.get_seq(),
            "context": self.get_context()
        }

    def get_identifier(self):
        return {
            "timestamp": self.get_timestamp(),
            "current_id": self.get_current_id(),
            "previous_id": self.get_previous_id(),
            "origin_id": self.get_origin_id()
        }

    def get_api_identifier(self) -> str:
        return f"{self.get_origin_id()}.{self.get_previous_id()}.{self.get_current_id()}"

    def get_subject(self):
        return self.get_value("metadata.reference.subject")

    def get_current_id(self) -> str:
        return self.get_value("metadata.reference.current_id")

    def get_origin_id(self) -> str:
        return self.get_value("metadata.reference.origin_id")

    def get_previous_id(self) -> str:
        return self.get_value("metadata.reference.previous_id")

    def get_timestamp(self) -> str:
        return self.get_value("metadata.reference.timestamp")

    def get_stream(self) -> str:
        return self.get_value("metadata.reference.stream")

    def get_seq(self) -> str:
        return self.get_value("metadata.reference.seq")

    def get_context(self) -> str:
        return self.get_value("metadata.reference.context", "default")

    def get_api_reference(self):
        return {
            "identifier": self.get_api_identifier(),
            "subject": self.get_subject(),
            "stream": self.get_stream(),
            "seq": self.get_seq(),
            "context": self.get_context()
        }

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
        payload = cls(payload_data, nats_pool=nats_pool)
        payload.set_reference(
            subject=subject,
            origin_id=origin_id,
            previous_id=current_id)
        if event_type:
            payload.set_event_type(event_type)
        if command_type:
            payload.set_command_type(command_type)
        return payload

    @classmethod
    def kv(cls, payload_data, nats_pool: NatsConnectionPool | NatsConfig = None):
        return cls(payload_data, nats_pool=nats_pool)
