import uuid
from datetime import datetime
from enum import Enum
from keyval import KeyVal
from appkey import AppKey, Metadata, Reference, EventType, CommandType, Spec
from natstream import NatsPool, NatsConnectionPool, NatsConfig, NatsStreamReference, ErrTimeout, PubAck, RawStreamMsg, \
    logger

PLAYBOOKS = AppKey.PLAYBOOKS
PLUGINS = AppKey.PLUGINS
PLUGIN_NAME = AppKey.PLUGIN_NAME
IMAGE_URL = AppKey.IMAGE_URL
PLAYBOOK_NAME = AppKey.PLAYBOOK_NAME
PLAYBOOK_BASE64 = AppKey.PLAYBOOK_BASE64
REVISION_NUMBER = AppKey.REVISION_NUMBER
VALUE = AppKey.VALUE
VALUE_NOT_FOUND = AppKey.VALUE_NOT_FOUND
ERROR = AppKey.ERROR
BLUEPRINT = AppKey.BLUEPRINT
BLUEPRINT_SPEC_INPUT = AppKey.BLUEPRINT_SPEC_INPUT
BLUEPRINT_NATS_KV_METADATA = AppKey.BLUEPRINT_NATS_KV_METADATA
PLAYBOOK_INPUT = AppKey.PLAYBOOK_INPUT
METADATA = AppKey.METADATA
METADATA_NOT_FOUND = AppKey.METADATA_NOT_FOUND
# EventTypes
PLUGIN_REGISTERED = EventType.PLUGIN_REGISTERED
PLAYBOOK_REGISTERED = EventType.PLAYBOOK_REGISTERED
PLAYBOOK_EXECUTION_REQUEST_FAILED = EventType.PLAYBOOK_EXECUTION_REQUEST_FAILED
PLAYBOOK_EXECUTION_REGISTERED = EventType.PLAYBOOK_EXECUTION_REGISTERED


class PayloadType(Enum):
    """
    PayloadType Enum class of payload type.
    Attributes:
        EVENT (str): Payload type for events.
        COMMAND (str): Payload type for commands.
    """
    EVENT = AppKey.EVENT
    COMMAND = AppKey.COMMAND


class Payload(KeyVal, NatsPool):
    """The Payload class is used to handle payloads.
    It inherits from the KeyVal and NatsPool classes.
    """

    def __init__(self,
                 *args,
                 nats_pool: NatsConnectionPool | NatsConfig = None,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.nats_reference: NatsStreamReference | None = None
        if nats_pool:
            self.initialize_nats_pool(nats_pool)

    @property
    def nats_reference(self):
        return self._nats_reference

    @nats_reference.setter
    def nats_reference(self, value: NatsStreamReference):
        self._nats_reference: NatsStreamReference = value

    def set_nats_pool(self, nats_pool: NatsConnectionPool | NatsConfig):
        if nats_pool:
            self.initialize_nats_pool(nats_pool)

    def get_reference(self):
        return self.get_value(Metadata.REFERENCE, default=VALUE_NOT_FOUND)

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

    def set_metadata(self, metadata: dict = None, exclude: list[str] = None):
        metadata_orig = self.get_value(AppKey.METADATA, exclude=exclude)
        if metadata_orig:
            metadata |= metadata_orig
        self.set_value(AppKey.METADATA, metadata)

    def add_metadata(self, key: str, value: any):
        self.set_value(f"{AppKey.METADATA}.{key}", value)

    def set_event_type(self, event_type):
        self.set_metadata(metadata={AppKey.EVENT_TYPE: event_type}, exclude=[AppKey.COMMAND_TYPE, AppKey.EVENT_TYPE])

    def set_command_type(self, command_type):
        self.set_metadata(metadata={AppKey.COMMAND_TYPE: command_type},
                          exclude=[AppKey.COMMAND_TYPE, AppKey.EVENT_TYPE])

    def set_nats_reference(self):
        self.set_metadata(metadata=self.nats_reference.to_dict(), exclude=AppKey.NATS_REFERENCE)

    async def snapshot_playbook(self):
        playbook_name = self.get_value(PLAYBOOK_NAME, default=VALUE_NOT_FOUND)
        if playbook_name not in [VALUE_NOT_FOUND, None]:
            kv_payload = await self.playbook_get(playbook_name)
            kv_payload = Payload.decode(kv_payload)
            playbook_template = kv_payload.yaml_value(PLAYBOOK_BASE64)
            if playbook_template == VALUE_NOT_FOUND:
                self.set_value(ERROR, f"Playbook template {playbook_name} was not found")
                self.set_event_type(event_type=PLAYBOOK_EXECUTION_REQUEST_FAILED)
            else:
                self.set_value(BLUEPRINT, playbook_template)
                self.set_value(BLUEPRINT_SPEC_INPUT, self.get_value(PLAYBOOK_INPUT))
                self.set_value(BLUEPRINT_NATS_KV_METADATA, kv_payload.get_value(METADATA, default=METADATA_NOT_FOUND))
                self.set_event_type(PLAYBOOK_EXECUTION_REGISTERED)

    async def payload_write(self,
                            event_type: str = None,
                            command_type: str = None,
                            message: bytes = None,
                            subject: str = None,
                            subject_prefix: str = None,
                            stream: str = None,
                            plugin: str = None):
        nats_prefix = None
        if subject_prefix:
            nats_prefix = subject_prefix
        if event_type:
            if subject_prefix is None and self.info:
                nats_prefix = self.info.get("nats_event_prefix")
            self.set_event_type(event_type)
        elif command_type:
            if subject_prefix is None and self.info:
                nats_prefix = self.info.get("nats_command_prefix")
            self.set_command_type(command_type)

        nats_prefix = nats_prefix or "noetl"

        reference = self.get_reference()

        if reference not in [VALUE_NOT_FOUND]:
            self.update_reference()
        else:
            self.set_reference()

        subject = subject or f"{nats_prefix}.{plugin}.{self.get_origin_id()}"

        self.set_subject(subject=subject)

        if stream is None:
            stream = self.info.get("nats_subscription_stream")
        self.set_stream(stream=stream)

        if self.nats_reference:
            self.set_nats_reference()

        if message is None:
            message = self.encode()
        ack = await self.nats_write(subject=subject, stream=stream, payload=message)
        logger.debug(ack)
        return ack

    async def command_write(self,
                            command_type: str = None,
                            message: bytes = None,
                            subject: str = None,
                            subject_prefix: str = None,
                            stream: str = None,
                            plugin: str = None):

        return await self.payload_write(command_type=command_type,
                                        message=message,
                                        subject=subject,
                                        subject_prefix=subject_prefix,
                                        stream=stream,
                                        plugin=plugin)

    async def event_write(self,
                          event_type: str = None,
                          message: bytes = None,
                          subject: str = None,
                          subject_prefix: str = None,
                          stream: str = None,
                          plugin: str = None):

        return await self.payload_write(event_type=event_type,
                                        message=message,
                                        subject=subject,
                                        subject_prefix=subject_prefix,
                                        stream=stream,
                                        plugin=plugin)

    async def playbook_bucket_create(self):
        await self.nats_pool.bucket_create(bucket_name=PLAYBOOKS)

    async def playbook_bucket_delete(self):
        await self.nats_pool.bucket_delete(bucket_name=PLAYBOOKS)

    async def playbook_put(self, key: str = None, value: bytes = None):
        revision = 0
        playbook_name = key or self.get_value(PLAYBOOK_NAME)
        playbook = value or self.encode(keys=[PLAYBOOK_BASE64, METADATA])
        if playbook_name and playbook:
            revision = await self.nats_pool.kv_put(bucket_name=PLAYBOOKS, key=playbook_name, value=playbook)
        self.set_event_type(event_type=PLAYBOOK_REGISTERED)
        self.set_value(REVISION_NUMBER, revision)

    async def playbook_get(self, key: str):
        return await self.nats_pool.kv_get(bucket_name=PLAYBOOKS, key=key)

    async def playbook_decode(self, key: str):
        kv_payload = await self.playbook_get(key)
        kv_payload_decoded = Payload.decode(kv_payload)
        return kv_payload_decoded.yaml_value(PLAYBOOK_BASE64)


    async def playbook_delete(self, key: str):
        await self.nats_pool.kv_delete(bucket_name=PLAYBOOKS, key=key)

    async def plugin_bucket_create(self):
        await self.nats_pool.bucket_create(bucket_name=PLUGINS)

    async def plugin_bucket_delete(self):
        await self.nats_pool.bucket_delete(bucket_name=PLUGINS)

    async def plugin_put(self, key: str = None, value: bytes = None):
        revision = 0
        plugin_name = key or self.get_value(PLUGIN_NAME)
        plugin_url = value or self.get_value(IMAGE_URL).encode()
        if plugin_name and plugin_url:
            revision = await self.nats_pool.kv_put(bucket_name=PLUGINS, key=plugin_name, value=plugin_url)
        self.set_event_type(event_type=PLUGIN_REGISTERED)
        self.set_value(REVISION_NUMBER, revision)

    async def plugin_get(self, key: str):
        return await self.nats_pool.kv_get(bucket_name=AppKey.PLUGINS, key=key)

    async def plugin_decode(self, key: str):
        kv_payload = await self.plugin_get(key=key)
        return kv_payload.decode()

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
