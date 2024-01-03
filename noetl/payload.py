import uuid
from datetime import datetime
from enum import Enum
from keyval import KeyVal
from appkey import AppKey, Metadata, Reference, EventType, CommandType, Spec
from natstream import NatsPool, NatsConnectionPool, NatsConfig, ErrTimeout, PubAck, RawStreamMsg


class PayloadType(Enum):
    """
    Enum class representing payload type.

    Attributes:
        EVENT (str): Payload type for events.
        COMMAND (str): Payload type for commands.
    """
    EVENT = AppKey.EVENT
    COMMAND = AppKey.COMMAND


class Payload(KeyVal, NatsPool):
    """A class representing a payload.

    The Payload class is used for handling payloads and inherits from the KeyVal and NatsPool classes.

    Args:
        *args: List of Arguments.
        nats_pool (NatsConnectionPool | NatsConfig, optional): An instance of NatsConnectionPool or NatsConfig class.
        **kwargs: Arbitrary keyword arguments.
    """

    def __init__(self,
                 *args,
                 nats_pool: NatsConnectionPool | NatsConfig = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        if nats_pool:
            self.initialize_nats_pool(nats_pool)

    def set_nats_pool(self, nats_pool: NatsConnectionPool | NatsConfig):
        if nats_pool:
            self.initialize_nats_pool(nats_pool)
    def get_reference(self):
        return self.get_keyval(Metadata.REFERENCE)

    def get_payload_reference(self):
        return self.get_identifier() | {
            AppKey.SUBJECT: self.get_subject(),
            AppKey.STREAM: self.get_stream(),
            AppKey.SEQ: self.get_seq(),
            AppKey.CONTEXT: self.get_context()
        }

    def get_identifier(self):
        return {
            AppKey.TIMESTAMP: self.get_timestamp(),
            AppKey.CURRENT_ID: self.get_current_id(),
            AppKey.PREVIOUS_ID: self.get_previous_id(),
            AppKey.ORIGIN_ID: self.get_origin_id()
        }

    def get_api_identifier(self) -> str:
        return f"{self.get_origin_id()}.{self.get_previous_id()}.{self.get_current_id()}"

    def get_subject(self):
        return self.get_value(Reference.SUBJECT)

    def get_current_id(self) -> str:
        return self.get_value(Reference.CURRENT_ID)

    def get_origin_id(self) -> str:
        return self.get_value(Reference.ORIGIN_ID)

    def get_previous_id(self) -> str:
        return self.get_value(Reference.PREVIOUS_ID)

    def get_timestamp(self) -> str:
        return self.get_value(Reference.TIMESTAMP)

    def get_stream(self) -> str:
        return self.get_value(Reference.STREAM)

    def get_seq(self) -> str:
        return self.get_value(Reference.SEQ)

    def get_context(self) -> str:
        return self.get_value(Reference.CONTEXT, AppKey.DEFAULT)

    def get_api_reference(self):
        return {
            AppKey.IDENTIFIER: self.get_api_identifier(),
            AppKey.SUBJECT: self.get_subject(),
            AppKey.STREAM: self.get_stream(),
            AppKey.SEQ: self.get_seq(),
            AppKey.CONTEXT: self.get_context()
        }

    def set_reference(self,
                      timestamp=None,
                      subject=None,
                      origin_id=None,
                      previous_id=None,
                      stream=None,
                      seq=None,
                      context=None):
        self.set_subject(subject)
        self.set_timestamp(timestamp)
        self.set_current_id()
        self.set_previous_id(previous_id)
        self.set_origin_id(origin_id)
        self.set_stream(stream)
        self.set_seq(seq)
        self.set_context(context)

    def update_reference(self):
        self.set_previous_id()
        self.set_current_id()
        self.get_timestamp()

    def set_subject(self, subject: str = None):
        if subject:
            self.set_value(Reference.SUBJECT, subject)

    def set_timestamp(self, timestamp: str = None):
        self.set_value(Reference.TIMESTAMP, timestamp if timestamp else str(int(datetime.now().timestamp() * 1000)))

    def set_current_id(self):
        self.set_value(Reference.CURRENT_ID, str(uuid.uuid4()))

    def set_previous_id(self, previous_id: str = None):
        self.set_value(Reference.PREVIOUS_ID, previous_id if previous_id else self.get_current_id())

    def set_origin_id(self, origin_id: str = None):
        self.set_value(Reference.ORIGIN_ID, origin_id if origin_id else self.get_current_id())

    def set_stream(self, stream=None):
        if stream:
            self.set_value(Reference.STREAM, stream)

    def set_seq(self, seq: str | int = None):
        if seq:
            self.set_value(Reference.SEQ, seq)

    def set_context(self, context: str | dict = None):
        if context:
            self.set_value(Reference.CONTEXT, context)

    def set_metadata(self, metadata: dict, exclude: list[str] = None):
        metadata = self.get_value(AppKey.METADATA, exclude=exclude) | metadata
        self.set_value(AppKey.METADATA, metadata)

    def set_event_type(self, event_type):
        self.set_metadata(metadata={AppKey.EVENT_TYPE: event_type}, exclude=[AppKey.COMMAND_TYPE, AppKey.EVENT_TYPE])

    def set_command_type(self, command_type):
        self.set_metadata(metadata={AppKey.COMMAND_TYPE: command_type},
                          exclude=[AppKey.COMMAND_TYPE, AppKey.EVENT_TYPE])

    async def snapshot_playbook(self, nats_reference: dict):
        playbook_name = self.get_value(AppKey.PLAYBOOK_NAME, default=AppKey.VALUE_NOT_FOUND)
        if playbook_name not in [AppKey.VALUE_NOT_FOUND, None]:
            kv_payload = Payload.decode(await self.playbook_get(playbook_name))
            playbook_template = kv_payload.yaml_value(AppKey.VALUE)
            if playbook_template == AppKey.VALUE_NOT_FOUND:
                self.set_value(AppKey.ERROR, f"Playbook template {playbook_name} was not found")
                self.set_event_type(event_type=EventType.PLAYBOOK_EXECUTION_REQUEST_FAILED)
            else:
                self.set_value(AppKey.BLUEPRINT, playbook_template)
                self.set_value(AppKey.BLUEPRINT_SPEC_INPUT, self.get_value(AppKey.PLAYBOOK_INPUT))
                self.set_value(AppKey.BLUEPRINT_NATS_KV_METADATA, kv_payload.get_value(AppKey.METADATA,
                                                                                  default=AppKey.METADATA_NOT_FOUND))
                self.set_metadata({AppKey.NATS_REFERENCE: nats_reference})
                self.set_event_type(event_type=EventType.PLAYBOOK_EXECUTION_REGISTERED)
        self.update_reference()

    async def plugin_bucket_create(self):
        await self.nats_pool.bucket_create(bucket_name=AppKey.PLUGINS)

    async def plugin_bucket_delete(self):
        await self.nats_pool.bucket_delete(bucket_name=AppKey.PLUGINS)

    async def plugin_put(self, key: str = None, value: bytes = None):
        revision = 0
        plugin_name = key or self.get_value(AppKey.PLUGIN_NAME)
        plugin_url = value or self.get_value(AppKey.IMAGE_URL).encode()
        if plugin_name and plugin_url:
            revision = await self.nats_pool.kv_put(bucket_name=AppKey.PLUGINS, key=plugin_name, value=plugin_url)
        self.set_event_type(event_type=EventType.PLUGIN_REGISTERED)
        self.set_value(AppKey.REVISION_NUMBER, revision)

    async def plugin_get(self, key: str):
        return await self.nats_pool.kv_get(bucket_name=AppKey.PLUGINS, key=key)

    async def plugin_delete(self, key: str):
        await self.nats_pool.kv_delete(bucket_name=AppKey.PLUGINS, key=key)
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
