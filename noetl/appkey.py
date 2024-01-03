class AppKey:
    BASE64 = "base64"
    BLUEPRINT="blueprint"
    BLUEPRINT_SPEC_INPUT="blueprint.spec.input"
    BLUEPRINT_NATS_KV_METADATA="blueprintNatsKvMetadata"
    COMMAND = "command"
    COMMAND_TYPE = "commandType"
    CONTEXT = "context"
    CURRENT_ID = "currentId"
    DATA = "data"
    DEFAULT = "default"
    DICT = "dict"
    DISPATCHER = "dispatcher"
    EVENT = "event"
    EVENT_TYPE = "eventType"
    ERROR = "error"
    HTTP_HANDLER = "http_handler"
    IDENTIFIER = "identifier"
    IMAGE_URL = "imageUrl"
    INPUT = "input"
    METADATA = "metadata"
    METADATA_NOT_FOUND = "metadataNotFound"
    NAME = "name"
    NATS_REFERENCE = "natsReference"
    NO_DATA_PROVIDED = "noDataProvided"
    ORIGIN_ID = "originId"
    OUTPUT = "output"
    PAYLOAD_BASE64 = "payloadBase64"
    PAYLOAD_REFERENCE = "payloadReference"
    PLAYBOOK = "playbook"
    PLAYBOOK_BASE64 = "playbookBase64"
    PLAYBOOK_INPUT = "playbookInput"
    PLAYBOOK_NAME = "playbookName"
    PLAYBOOK_METADATA = "playbookMetadata"
    PLAYBOOKS = "playbooks"
    PLAYBOOK_REFERENCE = "playbookReference"
    PLUGIN = "plugin"
    PLUGIN_NAME = "pluginName"
    PLUGINS = "plugins"
    PREVIOUS_ID = "previousId"
    REGISTRAR = "registrar"
    REFERENCE = "reference"
    REVISION_NUMBER = "revisionNumber"
    SEQ = "seq"
    STREAM = "stream"
    SUBJECT = "subject"
    TIMESTAMP = "timestamp"
    TOKENS = "tokens"
    UTF_8 = "utf-8"
    VALUE = "value"
    VALUE_NOT_FOUND = "valueNotFound"
    VALUE_TYPE = "valueType"


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
    PLAYBOOK_EXECUTION_REQUEST_FAILED = "PlaybookExecutionRequestFailed"
    PLAYBOOK_REGISTRATION_REQUESTED = "PlaybookRegistrationRequested"
    PLAYBOOK_EXECUTION_REQUESTED = "PlaybookExecutionRequested"
    PLUGIN_REGISTRATION_REQUESTED = "PluginRegistrationRequested"
    PLAYBOOK_REGISTERED="PlaybookRegistered"
    PLUGIN_REGISTERED="PluginRegistered"
    PLAYBOOK_EXECUTION_REGISTERED="PlaybookExecutionRegistered"


class CommandType:
    REGISTER_PLAYBOOK = "RegisterPlaybook"
    REGISTER_PLUGIN = "RegisterPlugin"
    REGISTER_PLAYBOOK_EXECUTION = "RegisterPlaybookExecution"


class Spec:
    SPEC_ID = "spec.id"
    SPEC_REFERENCE = "spec.reference"
    SPEC_REFERENCE_SEQ = "spec.reference.seq"
    SPEC_REFERENCE_STREAM = "spec.reference.stream"
    SPEC_INPUT = "spec.input"
