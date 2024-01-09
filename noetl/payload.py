import uuid
from datetime import datetime
from enum import Enum
from keyval import KeyVal
from const import AppConst
from natstream import NatsPool, NatsConnectionPool, NatsConfig, NatsStreamReference, ErrTimeout, PubAck, RawStreamMsg, \
    logger

PLAYBOOKS = AppConst.PLAYBOOKS
PLUGINS = AppConst.PLUGINS
PLUGIN_NAME = AppConst.PLUGIN_NAME
IMAGE_URL = AppConst.IMAGE_URL
PLAYBOOK_NAME = AppConst.PLAYBOOK_NAME
PLAYBOOK_BASE64 = AppConst.PLAYBOOK_BASE64
REVISION_NUMBER = AppConst.REVISION_NUMBER
VALUE = AppConst.VALUE
VALUE_NOT_FOUND = AppConst.VALUE_NOT_FOUND
ERROR = AppConst.ERROR
BLUEPRINT = AppConst.BLUEPRINT
BLUEPRINT_SPEC_INPUT = AppConst.BLUEPRINT_SPEC_INPUT
BLUEPRINT_NATS_KV_METADATA = AppConst.BLUEPRINT_NATS_KV_METADATA
PLAYBOOK_INPUT = AppConst.PLAYBOOK_INPUT
METADATA = AppConst.METADATA
METADATA_REFERENCE = AppConst.METADATA_REFERENCE
METADATA_NOT_FOUND = AppConst.METADATA_NOT_FOUND
METADATA_REFERENCE_SUBJECT=AppConst.METADATA_REFERENCE_SUBJECT
METADATA_REFERENCE_CONTEXT=AppConst.METADATA_REFERENCE_CONTEXT
METADATA_REFERENCE_CURRENT_ID=AppConst.METADATA_REFERENCE_CURRENT_ID
METADATA_REFERENCE_ORIGIN_ID=AppConst.METADATA_REFERENCE_ORIGIN_ID
METADATA_REFERENCE_PREVIOUS_ID=AppConst.METADATA_REFERENCE_PREVIOUS_ID
METADATA_REFERENCE_SEQ=AppConst.METADATA_REFERENCE_SEQ
METADATA_REFERENCE_STREAM=AppConst.METADATA_REFERENCE_STREAM
METADATA_REFERENCE_TIMESTAMP=AppConst.METADATA_REFERENCE_TIMESTAMP
NATS_REFERENCE=AppConst.NATS_REFERENCE


EVENT_TYPE=AppConst.EVENT_TYPE
COMMAND_TYPE=AppConst.COMMAND_TYPE
METADATA_EVENT_TYPE=AppConst.METADATA_EVENT_TYPE
METADATA_COMMAND_TYPE=AppConst.METADATA_COMMAND_TYPE

# Events
EVENT_PLUGIN_REGISTERED = AppConst.EVENT_PLUGIN_REGISTERED
EVENT_PLAYBOOK_REGISTERED = AppConst.EVENT_PLAYBOOK_REGISTERED
EVENT_PLAYBOOK_EXECUTION_REQUEST_FAILED = AppConst.EVENT_PLAYBOOK_EXECUTION_REQUEST_FAILED
EVENT_PLAYBOOK_EXECUTION_REGISTERED = AppConst.EVENT_PLAYBOOK_EXECUTION_REGISTERED


class PayloadType(Enum):
    """
    PayloadType Enum class of payload type.
    Attributes:
        EVENT (str): Payload type for events.
        COMMAND (str): Payload type for commands.
    """
    EVENT = AppConst.EVENT
    COMMAND = AppConst.COMMAND


class Payload(KeyVal, NatsPool):
    """The Payload class is used to handle payloads.
    Inherits the KeyVal and NatsPool classes.
    """

    def __init__(self,
                 nats_pool: NatsConnectionPool | NatsConfig | None = None,
                 payload_data: str | dict | list | None = None,
                 event_type: str | None = None,
                 command_type: str | None = None,
                 *args,
                 **kwargs):

        super().__init__(payload_data, *args, **kwargs) if payload_data else super().__init__(self,*args, **kwargs)
        if nats_pool:
            self.initialize_nats_pool(nats_pool)
        self.nats_reference: NatsStreamReference | None = None
        if event_type:
            self.set_event_type(event_type)
        elif command_type:
            self.set_command_type(command_type)

    @property
    def nats_reference(self):
        return self._nats_reference

    @nats_reference.setter
    def nats_reference(self, nats_stream_reference: NatsStreamReference):
        self._nats_reference: NatsStreamReference = nats_stream_reference

    def set_nats_pool(self, nats_pool: NatsConnectionPool | NatsConfig):
        if nats_pool:
            self.initialize_nats_pool(nats_pool)

    def get_reference(self):
        return self.get_value(METADATA_REFERENCE, default=VALUE_NOT_FOUND)

    def get_payload_reference(self):
        return self.get_identifier() | {
            AppConst.SUBJECT: self.get_subject(),
            AppConst.STREAM: self.get_stream(),
            AppConst.SEQ: self.get_seq(),
            AppConst.CONTEXT: self.get_context()
        }

    def get_identifier(self):
        return {
            AppConst.TIMESTAMP: self.get_timestamp(),
            AppConst.CURRENT_ID: self.get_current_id(),
            AppConst.PREVIOUS_ID: self.get_previous_id(),
            AppConst.ORIGIN_ID: self.get_origin_id()
        }

    def get_api_identifier(self) -> str:
        return f"{self.get_origin_id()}.{self.get_previous_id()}.{self.get_current_id()}"

    def get_subject(self):
        return self.get_value(METADATA_REFERENCE_SUBJECT)

    def get_current_id(self) -> str:
        return self.get_value(METADATA_REFERENCE_CURRENT_ID)

    def get_origin_id(self) -> str:
        return self.get_value(METADATA_REFERENCE_ORIGIN_ID)

    def get_previous_id(self) -> str:
        return self.get_value(METADATA_REFERENCE_PREVIOUS_ID)

    def get_timestamp(self) -> str:
        return self.get_value(METADATA_REFERENCE_TIMESTAMP)

    def get_stream(self) -> str:
        return self.get_value(METADATA_REFERENCE_STREAM)

    def get_seq(self) -> str:
        return self.get_value(METADATA_REFERENCE_SEQ)

    def get_context(self) -> str:
        return self.get_value(METADATA_REFERENCE_CONTEXT, AppConst.DEFAULT)

    def get_api_reference(self):
        return {
            AppConst.IDENTIFIER: self.get_api_identifier(),
            AppConst.SUBJECT: self.get_subject(),
            AppConst.STREAM: self.get_stream(),
            AppConst.SEQ: self.get_seq(),
            AppConst.CONTEXT: self.get_context()
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
        self.set_previous_id(previous_id=self.get_current_id())
        self.set_current_id()
        self.set_timestamp()

    def set_subject(self, subject: str = None):
        if subject:
            self.set_value(METADATA_REFERENCE_SUBJECT, subject)

    def set_timestamp(self, timestamp: str = None):
        self.set_value(METADATA_REFERENCE_TIMESTAMP, timestamp or str(int(datetime.now().timestamp() * 1000)))

    def set_current_id(self):
        self.set_value(METADATA_REFERENCE_CURRENT_ID, str(uuid.uuid4()))

    def set_previous_id(self, previous_id: str = None):
        self.set_value(METADATA_REFERENCE_PREVIOUS_ID, previous_id or self.get_current_id())

    def set_origin_id(self, origin_id: str = None):
        self.set_value(METADATA_REFERENCE_ORIGIN_ID, origin_id or self.get_current_id())

    def set_stream(self, stream=None):
        if stream:
            self.set_value(METADATA_REFERENCE_STREAM, stream)

    def set_seq(self, seq: str | int = None):
        if seq:
            self.set_value(METADATA_REFERENCE_SEQ, seq)

    def set_context(self, context: str | dict = None):
        if context:
            self.set_value(METADATA_REFERENCE_CONTEXT, context)

    def set_metadata(self, metadata: dict = None, exclude: list[str] = None):
        metadata_orig = self.get_value(METADATA, exclude=exclude)
        if metadata_orig and metadata:
            metadata |= metadata_orig
        self.set_value(METADATA, metadata)

    def add_metadata_value(self, key: str = None, value: any = None):
        if key and value:
            self.set_value(f"{METADATA}.{key}", value)

    def delete_metadata_keys(self, keys: list):
        for key in keys:
            self.delete_value(path=f"{METADATA}.{key}")

    def set_event_type(self, event_type: str = None):
        if event_type:
            self.delete_metadata_keys(keys=list([EVENT_TYPE, COMMAND_TYPE]))
            self.add_metadata_value(EVENT_TYPE, event_type)

    def set_command_type(self, command_type: str = None):
        if command_type:
            self.delete_metadata_keys(keys=list([EVENT_TYPE, COMMAND_TYPE]))
            self.add_metadata_value(COMMAND_TYPE, command_type)

    def set_nats_reference(self):
        self.set_metadata(metadata=self.nats_reference.to_dict(), exclude=NATS_REFERENCE)

    async def snapshot_playbook(self):
        playbook_name = self.get_value(PLAYBOOK_NAME, default=VALUE_NOT_FOUND)
        if playbook_name not in [VALUE_NOT_FOUND, None]:
            kv_payload = await self.playbook_get(playbook_name)
            kv_payload = Payload.decode(kv_payload)
            playbook_template = kv_payload.yaml_value(PLAYBOOK_BASE64)
            if playbook_template == VALUE_NOT_FOUND:
                self.set_value(ERROR, f"Playbook template {playbook_name} was not found")
                self.set_event_type(event_type=EVENT_PLAYBOOK_EXECUTION_REQUEST_FAILED)
            else:
                self.set_value(BLUEPRINT, playbook_template)
                self.set_value(BLUEPRINT_SPEC_INPUT, self.get_value(PLAYBOOK_INPUT))
                self.set_value(BLUEPRINT_NATS_KV_METADATA, kv_payload.get_value(METADATA, default=METADATA_NOT_FOUND))
                self.set_event_type(EVENT_PLAYBOOK_EXECUTION_REGISTERED)

    async def payload_write(self,
                            event_type: str = None,
                            command_type: str = None,
                            message: bytes = None,
                            subject: str = None,
                            subject_prefix: str = None,
                            stream: str = None,
                            plugin: str = None):
        if subject_prefix:
            nats_prefix = subject_prefix
        elif self.info:
            prefix_key = "nats_event_prefix" if event_type else "nats_command_prefix"
            nats_prefix = self.info.get(prefix_key, "noetl")
        else:
            nats_prefix = "noetl"

        if event_type:
            self.set_event_type(event_type)
        elif command_type:
            self.set_command_type(command_type)

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
        self.set_event_type(event_type=EVENT_PLAYBOOK_REGISTERED)
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
        plugin = value or self.encode(keys=[PLUGIN_NAME, IMAGE_URL, METADATA])
        if plugin_name and plugin:
            revision = await self.nats_pool.kv_put(bucket_name=PLUGINS, key=plugin_name, value=plugin)
        self.set_event_type(event_type=EVENT_PLUGIN_REGISTERED)
        self.set_value(REVISION_NUMBER, revision)

    async def plugin_get(self, key: str):
        return await self.nats_pool.kv_get(bucket_name=PLUGINS, key=key)

    async def plugin_decode(self, key: str):
        kv_payload = await self.plugin_get(key=key)
        return kv_payload.decode()

    async def plugin_delete(self, key: str):
        await self.nats_pool.kv_delete(bucket_name=PLUGINS, key=key)
