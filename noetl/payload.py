import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from keyval import KeyVal
from natstream import NatsPool, NatsConnectionPool, NatsConfig

class PayloadType(Enum):
    EVENT = "event"
    COMMAND = "command"
@dataclass
class PayloadReference:
    """
    The reference structure for payload identifiers in a workflow.

    Attributes:
        origin: The ID of the first event in the workflow, the root or starting point.
        reference: The ID of the predecessor event.
        identifier: The unique ID of the current event or workflow instance.
        timestamp: The Unix timestamp of the payload creation time.

    NATS Stream Key Format:
        The format for NATS streams is '<stream name>.<plugin name>.<origin>.<identifier>',
        where each part represents specific identifiers related to the workflow instance and step.

    Examples of NATS Stream Keys:
        - 'event.dispatcher.12345.abcde' (for an event stream)
        - 'command.http-handler.12345.bcdef' (for a command stream)
    """

    origin: str = None
    """The origin identifier of the root event in the workflow sequence."""

    reference: str = None
    """The reference identifier of the immediate predecessor event."""

    identifier: str = None
    """The unique identifier of the current event or instance."""

    timestamp: str = None
    """The Unix timestamp of the payload creation time."""

    def __init__(self, origin=None, reference=None, timestamp=None, identifier=None):
        self.timestamp = timestamp if timestamp else str(int(datetime.now().timestamp() * 1000))
        self.identifier = identifier if identifier else str(uuid.uuid4())
        self.reference = reference if reference else self.identifier
        self.origin = origin if origin else self.identifier

    def update(self):
        """
        Creates a new PayloadReference instance with updated values.

        Returns:
            PayloadReference: A new instance with updated timestamp, identifier, and reference.
        """
        return PayloadReference(
            origin=self.origin,
            reference=self.identifier
        )

    def get_ref(self):
        """
        Returns the reference structure.

        Returns:
            dict: timestamp, identifier, reference, and origin.
        """
        return {
            "timestamp": self.timestamp,
            "identifier": self.identifier,
            "reference": self.reference,
            "origin": self.origin
        }


class Payload(KeyVal, NatsPool):

    def __init__(self, *args, nats_pool: NatsConnectionPool | NatsConfig = None, **kwargs):
        super().__init__(*args, **kwargs)
        if nats_pool:
            self.initialize_nats_pool(nats_pool)

    def set_ref(self, reference: PayloadReference):
        self.set_value("metadata.ref", reference.get_ref())

    def get_payload_reference(self):
        return self.get_ref()

    def get_subject_ref(self):
        origin = self.get_origin_ref()
        identifier = self.get_value("metadata.ref.identifier")
        return f"{origin}.{identifier}"

    def get_origin_ref(self):
        return self.get_value("metadata.ref.origin")

    def get_ref(self):
        return self.get_value("metadata.ref")

    def set_event_type(self, event_type):
        self.set_value("metadata.event_type", event_type)

    def set_command_type(self, command_type):
        self.set_value("metadata.command_type", command_type)

    @classmethod
    def create(cls,
               payload_data,
               nats_pool: NatsConnectionPool | NatsConfig = None,
               origin=None,
               reference=None,
               event_type=None,
               command_type=None
               ):
        payload_reference = PayloadReference(origin=origin, reference=reference)
        payload = cls(payload_data, nats_pool=nats_pool)
        payload.set_ref(reference=payload_reference)
        if event_type:
            payload.set_event_type(event_type)
        if command_type:
            payload.set_command_type(command_type)
        return payload

    @classmethod
    def kv(cls, payload_data, nats_pool: NatsConnectionPool | NatsConfig = None):
        return cls(payload_data, nats_pool=nats_pool)
