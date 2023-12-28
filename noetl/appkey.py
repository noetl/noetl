class AppKey:
    BASE64 = "base64"
    COMMAND = "command"
    COMMAND_TYPE = "command_type"
    CONTEXT = "context"
    CURRENT_ID = "current_id"
    DATA = "data"
    DEFAULT = "default"
    DICT = "dict"
    DISPATCHER = "dispatcher"
    EVENT = "event"
    EVENT_TYPE = "event_type"
    ERROR = "error"
    HTTP_HANDLER = "http_handler"
    IDENTIFIER = "identifier"
    IMAGE_URL = "image_url"
    INPUT = "input"
    METADATA = "metadata"
    METADATA_NOT_FOUND = "metadata_not_found"
    NAME = "name"
    NATS_REFERENCE = "nats_reference"
    NO_DATA_PROVIDED = "no_data_provided"
    ORIGIN_ID = "origin_id"
    OUTPUT = "output"
    PAYLOAD_BASE64 = "payload_base64"
    PAYLOAD_REFERENCE = "payload_reference"
    PLAYBOOK = "playbook"
    PLAYBOOK_BASE64 = "playbook_base64"
    PLAYBOOK_INPUT = "playbook_input"
    PLAYBOOK_NAME = "playbook_name"
    PLAYBOOK_METADATA = "playbook_metadata"
    PLAYBOOKS = "playbooks"
    PLAYBOOK_REFERENCE = "playbook_reference"
    PLUGIN = "plugin"
    PLUGIN_NAME = "plugin_name"
    PLUGINS = "plugins"
    PREVIOUS_ID = "previous_id"
    REGISTRAR = "registrar"
    REFERENCE = "reference"
    REVISION_NUMBER = "revision_number"
    SEQ = "seq"
    STREAM = "stream"
    SUBJECT = "subject"
    TIMESTAMP = "timestamp"
    TOKENS = "tokens"
    UTF_8 = "utf-8"
    VALUE = "value"
    VALUE_NOT_FOUND = "value_not_found"
    VALUE_TYPE = "value_type"


class Metadata:
    METADATA = AppKey.METADATA
    REFERENCE = f"{METADATA}.{AppKey.REFERENCE}"
    REVISION_NUMBER = f"{METADATA}.{AppKey.REVISION_NUMBER}"
    TOKENS = f"{METADATA}.{AppKey.TOKENS}"
    PLAYBOOK_NAME = f"{METADATA}.{AppKey.PLAYBOOK_NAME}"
    EVENT_TYPE = f"{METADATA}.{AppKey.EVENT_TYPE}"
    COMMAND_TYPE = f"{METADATA}.{AppKey.COMMAND_TYPE}"
    NAME = f"{METADATA}.{AppKey.NAME}"

    def __repr__(self):
        return AppKey.METADATA


class Reference:
    REFERENCE = AppKey.REFERENCE
    CONTEXT = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.CONTEXT}"
    CURRENT_ID = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.CURRENT_ID}"
    ORIGIN_ID = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.ORIGIN_ID}"
    PREVIOUS_ID = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.PREVIOUS_ID}"
    SEQ = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.SEQ}"
    STREAM = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.STREAM}"
    SUBJECT = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.SUBJECT}"
    TIMESTAMP = f"{Metadata.METADATA}.{REFERENCE}.{AppKey.TIMESTAMP}"

    def __repr__(self):
        return f"{AppKey.METADATA}.{AppKey.REFERENCE}"


class EventType:
    RUN_PLAYBOOK_REGISTRATION_FAILED = "RunPlaybookRegistrationFailed"
    PLAYBOOK_REGISTRATION_REQUESTED = "PlaybookRegistrationRequested"
    PLAYBOOK_EXECUTION_REQUESTED = "PlaybookExecutionRequested"
    PLUGIN_REGISTRATION_REQUESTED = "PluginRegistrationRequested"
    PLAYBOOK_REGISTERED="PlaybookRegistered"
    PLUGIN_REGISTERED="PluginRegistered"
    RUN_PLAYBOOK_REGISTERED="RunPlaybookRegistered"


class CommandType:
    REGISTER_PLAYBOOK = "RegisterPlaybook"
    REGISTER_PLUGIN = "RegisterPlugin"
    REGISTER_RUN_PLAYBOOK = "RegisterRunPlaybook"


class Spec:
    SPEC_ID = "spec.id"
    SPEC_REFERENCE = "spec.reference"
    SPEC_REFERENCE_SEQ = "spec.reference.seq"
    SPEC_REFERENCE_STREAM = "spec.reference.stream"
    SPEC_INPUT = "spec.input"
