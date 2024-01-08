import uuid
import asyncio
import strawberry
from loguru import logger
from pydantic import BaseModel
import spacy
from strawberry.scalars import JSON
from strawberry.types import Info
from payload import Payload, NatsConnectionPool, ErrTimeout, PubAck, AppConst

METADATA = AppConst.METADATA
PLAYBOOK_NAME = AppConst.PLAYBOOK_NAME
PLUGIN_NAME = AppConst.PLUGIN_NAME
IMAGE_URL = AppConst.IMAGE_URL
PLAYBOOK_BASE64 = AppConst.PLAYBOOK_BASE64
NAME = AppConst.NAME
PLAYBOOK_INPUT = AppConst.PLAYBOOK_INPUT
TOKENS = AppConst.TOKENS
DISPATCHER = AppConst.DISPATCHER
REVISION_NUMBER = AppConst.REVISION_NUMBER
EVENT_TYPE = AppConst.EVENT_TYPE
METADATA_EVENT_TYPE = AppConst.METADATA_EVENT_TYPE

# events

EVENT_PLAYBOOK_EXECUTION_REQUESTED = AppConst.EVENT_PLAYBOOK_EXECUTION_REQUESTED
EVENT_PLAYBOOK_REGISTRATION_REQUESTED = AppConst.EVENT_PLAYBOOK_REGISTRATION_REQUESTED
EVENT_PLUGIN_REGISTRATION_REQUESTED = AppConst.EVENT_PLUGIN_REGISTRATION_REQUESTED


class Command:
    class Tokenizer:
        def __init__(self):
            self.nlp = spacy.load("en_core_web_sm")

        def get_tokens(self, command_text):
            doc = self.nlp(command_text.lower())
            return [token.text for token in doc]

    class Structures:
        command_structures = {
            "register_playbook": ["register", "playbook", str],
            "run_playbook": ["run", "playbook", str],
            "describe_playbook": ["describe", "playbook", str],
            "show_workflow": ["show", "workflow", str],
            "status_workflow": ["status", "workflow", str],
            "append_data_to_workflow": ["append", "data", "to", "workflow", str],
            "kill_workflow": ["kill", "workflow", str],
            "unregister_playbook": ["drop", "playbook", str],
            "list_playbooks": ["list", "playbooks"],
            "list_events": ["list", "events"],
            "list_commands": ["list", "commands"],
            "list_plugins": ["list", "plugins"],
            "delete_events": ["delete", "events"],
            "delete_commands": ["delete", "commands"],
            "register_plugin": ["register", "plugin", str],
            "describe_plugin": ["describe", "plugin", str],
            "unregister_plugin": ["delete", "plugin", str]
        }

        @classmethod
        def match_structure(cls, tokens):
            match_command = None
            match_token_count = 0
            for function_name, structure in cls.command_structures.items():
                match_length = min(len(tokens), len(structure) - 1)
                is_valid = all(
                    t1 == t2 or isinstance(t2, type) and isinstance(t1, t2)
                    for t1, t2 in zip(tokens[:match_length], structure)
                )
                if is_valid and match_length >= match_token_count:
                    match_command = function_name
                    match_token_count = match_length
            return match_command, match_token_count


class InputValidationResult(BaseModel):
    is_valid: bool = False
    function_name: str | None = None
    message: str | None = None


class Input(BaseModel):
    tokens: str
    metadata: dict
    payload: str | list | dict


def validate_command(command_text):
    tokenizer = Command.Tokenizer()
    tokens = tokenizer.get_tokens(command_text)
    if not tokens:
        return InputValidationResult()
    match_command, match_token_count = Command.Structures.match_structure(tokens)
    if match_command:
        return InputValidationResult(
            is_valid=True, function_name=match_command, message=" ".join(tokens[match_token_count:])
        )
    else:
        return InputValidationResult()


@strawberry.type
class ResponseMessage:
    message: JSON


@strawberry.type
class RegistrationResponse:
    reference: JSON | None = None
    kind: str | None = None
    name: str | None = None
    event_type: str | None = None
    status: str | None = None
    message: str | None = None

    def to_dict(self):
        return {
            "reference": self.reference,
            "kind": self.kind,
            "name": self.name,
            "eventType": self.event_type,
            "status": self.status,
            "message": self.message}


@strawberry.type
class PlaybookMutations:
    """
    GraphQL Mutations for NoETL Playbooks.
    """

    @strawberry.mutation
    async def register_playbook(self,
                                playbook_base64: str,
                                info: Info,
                                metadata: JSON | None = strawberry.UNSET,
                                tokens: str | None = strawberry.UNSET,
                                ) -> RegistrationResponse:
        logger.debug(f"{TOKENS}: {tokens}, {METADATA}: {metadata}, {PLAYBOOK_BASE64}: {playbook_base64}")
        pool = NatsConnectionPool.get_instance()
        if pool is None:
            raise ValueError("NatsPool is not initialized")
        command_validation_result: InputValidationResult = validate_command(tokens)
        if command_validation_result.function_name == "register_playbook":
            try:
                nats_payload = Payload(nats_pool=pool)
                nats_payload.info = vars(info.context)
                playbook = Payload.base64_yaml(playbook_base64)
                logger.debug(playbook)
                playbook_name = playbook.get(METADATA).get(NAME)
                if playbook_name is None:
                    raise ValueError("playbook name is missing in the YAML.")
                nats_payload.set_value(PLAYBOOK_NAME, playbook_name)
                nats_payload.set_value(PLAYBOOK_BASE64, playbook_base64)
                nats_payload.set_metadata(metadata=metadata)
                nats_payload.add_metadata_value(PLAYBOOK_NAME, playbook_name)
                nats_payload.add_metadata_value(TOKENS, tokens)

                ack: PubAck = await nats_payload.event_write(
                    subject_prefix=info.context.nats_event_prefix,
                    stream=info.context.nats_event_stream,
                    plugin=DISPATCHER,
                    event_type=EVENT_PLAYBOOK_REGISTRATION_REQUESTED
                )
                registration_response = RegistrationResponse(
                    reference=nats_payload.get_api_reference() | ack.as_dict(),
                    kind="Playbook",
                    name=nats_payload.get_value(PLAYBOOK_NAME),
                    event_type=EVENT_PLAYBOOK_REGISTRATION_REQUESTED,
                    status="PlaybookRegistrationRequested",
                    message="Playbook registration has been successfully requested"
                )
                logger.info(f"Ack: {registration_response}")
                return registration_response

            except Exception as e:
                logger.error(f"Request failed due to error: {str(e)}")
                raise ValueError(f"Request failed due to error: {str(e)}")
        else:
            logger.error(f"Request IS NOT added {tokens}")
            raise ValueError(f"Request IS NOT added {tokens}")

    @strawberry.mutation
    async def delete_playbook(self, playbook_id: str) -> str:
        pass


@strawberry.type
class PlaybookQueries:
    @strawberry.field
    async def list_playbooks(self) -> JSON:
        """
        Retrieves list all playbooks in the NATS KV store.
        """
        pool = NatsConnectionPool.get_instance()
        try:
            keys = await pool.kv_get_all(AppConst.PLAYBOOKS)
            return {AppConst.PLAYBOOKS: keys}
        except Exception as e:
            logger.error(f"Error listing playbooks: {e}")
            return {"error": str(e)}

    @strawberry.input(
        name="DescribePlaybookInput",
        description="Describes playbook by name and optionally by revision")
    class DescribePlaybook:
        playbook_name: str
        revision: str | None = strawberry.UNSET
        metadata: JSON | None = strawberry.UNSET
        tokens: str | None = strawberry.UNSET

    @strawberry.field
    async def describe_playbook(self, playbook_input: DescribePlaybook) -> JSON:
        """
        Retrieves details of a playbook by playbook name.
        """
        pool = NatsConnectionPool.get_instance()
        try:
            if playbook_input.playbook_name:
                kv_payload = await pool.kv_get(AppConst.PLAYBOOKS, playbook_input.playbook_name)
                return {AppConst.PLAYBOOK: Payload.decode(kv_payload)}
            else:
                return {"error": "playbook name is required"}
        except Exception as e:
            logger.error(f"Error describing playbook {playbook_input.playbook_name}: {e}")
            return {"error": str(e)}

    @strawberry.input(
        name="RunPlaybookInput",
        description="Runs playbook by name with optional input parameters")
    class RunPlaybookInput:
        playbook_name: str
        metadata: JSON | None = strawberry.UNSET
        input: JSON | None = strawberry.UNSET
        tokens: str | None = strawberry.UNSET
        revision: str | None = strawberry.UNSET

    @strawberry.field
    async def run_playbook(
            self,
            run_playbook_input: RunPlaybookInput,
            info: Info
    ) -> RegistrationResponse:
        """
        Requests to execute a playbook by playbook name.
        """
        pool = NatsConnectionPool.get_instance()
        if pool is None:
            raise ValueError("NatsPool is not initialized")
        try:
            nats_payload = Payload(nats_pool=pool)
            nats_payload.info = vars(info.context)

            if run_playbook_input.playbook_name in [strawberry.UNSET, None]:
                raise ValueError("playbook name is missing.")
            else:
                nats_payload.set_value(PLAYBOOK_NAME,run_playbook_input.playbook_name)

            if run_playbook_input.input not in [strawberry.UNSET, None]:
                nats_payload.set_value(PLAYBOOK_INPUT, run_playbook_input.input)

            if run_playbook_input.metadata not in [strawberry.UNSET, None]:
                nats_payload.set_metadata(metadata=run_playbook_input.metadata)

            if run_playbook_input.tokens not in [strawberry.UNSET, None]:
                nats_payload.add_metadata_value(TOKENS, run_playbook_input.tokens)

            if run_playbook_input.revision not in [strawberry.UNSET, None]:
                nats_payload.add_metadata_value(REVISION_NUMBER, run_playbook_input.revision)

            ack: PubAck = await nats_payload.event_write(
                subject_prefix=info.context.nats_event_prefix,
                stream=info.context.nats_event_stream,
                plugin=DISPATCHER,
                event_type=EVENT_PLAYBOOK_EXECUTION_REQUESTED
            )

            reference = nats_payload.get_api_reference() | ack.as_dict(),
            registration_response = RegistrationResponse(
                reference=reference,
                kind="Playbook",
                name=nats_payload.get_value(PLAYBOOK_NAME),
                event_type=EVENT_PLAYBOOK_EXECUTION_REQUESTED,
                status="PlaybookExecutionRequested",
                message="Playbook execution has been successfully requested"
            )
            logger.info(f"Ack: {registration_response}")
            return registration_response

        except Exception as e:
            logger.error(f"Request failed due to error: {str(e)}")
            raise ValueError(f"Request failed due to error: {str(e)}")


@strawberry.type
class PluginMutations:
    @strawberry.input(
        name="PluginRegistrationInput",
        description="Register plugin by name and image reference parameters")
    class PluginRegistrationInput:
        plugin_name: str
        image_url: str
        metadata: JSON | None = strawberry.UNSET
        tokens: str | None = strawberry.UNSET

    @strawberry.mutation
    async def register_plugin(self,
                              registration_input: PluginRegistrationInput,
                              info: Info) -> RegistrationResponse:

        logger.debug(f"{PLUGIN_NAME}: {registration_input.plugin_name}, "
                     f"{IMAGE_URL}: {registration_input.image_url}, "
                     f"{METADATA}: {registration_input.metadata}")

        pool = NatsConnectionPool.get_instance()

        if pool is None:
            raise ValueError("NatsPool is not initialized")

        command_validation_result: InputValidationResult = validate_command(registration_input.tokens)

        if command_validation_result.function_name == "register_plugin":
            try:
                nats_payload = Payload(nats_pool=pool)
                nats_payload.info = vars(info.context)

                if registration_input.plugin_name in [None, strawberry.UNSET]:
                    raise ValueError("Plugin name is missing.")
                nats_payload.set_value(PLUGIN_NAME, registration_input.plugin_name)

                if registration_input.image_url in [None, strawberry.UNSET]:
                    raise ValueError("Plugin image url is missing.")
                nats_payload.set_value(IMAGE_URL, registration_input.image_url)

                if registration_input.metadata not in [None, strawberry.UNSET]:
                    nats_payload.set_metadata(metadata=registration_input.metadata)

                if registration_input.tokens not in [None, strawberry.UNSET]:
                    nats_payload.add_metadata_value(TOKENS, registration_input.tokens)

                ack: PubAck = await nats_payload.event_write(
                    event_type=EVENT_PLUGIN_REGISTRATION_REQUESTED,
                    subject_prefix=info.context.nats_event_prefix,
                    stream=info.context.nats_event_stream,
                    plugin=DISPATCHER
                )
                reference = nats_payload.get_api_reference() | ack.as_dict(),

                registration_response = RegistrationResponse(
                    reference=reference,
                    kind="Plugin",
                    name=nats_payload.get_value(AppConst.PLUGIN_NAME),
                    event_type=nats_payload.get_value(METADATA_EVENT_TYPE),
                    status="PluginRegistrationRequested",
                    message="Plugin registration has been successfully requested"
                )

                logger.info(f"Ack: {registration_response}")
                return registration_response

            except Exception as e:
                logger.error(f"Request failed due to error: {str(e)}")
                raise ValueError(f"Request failed due to error: {str(e)}")
        else:
            logger.error(f"Request IS NOT added {registration_input.tokens}")
            raise ValueError(f"Request IS NOT added {registration_input.tokens}")

    @strawberry.mutation
    async def delete_plugin(self, plugin_id: str) -> str:
        pass


@strawberry.type
class PluginQueries:

    @strawberry.field
    async def list_plugins(self) -> JSON:
        """
        Retrieves list all plugins in the NATS KV store.
        """
        pool = NatsConnectionPool.get_instance()
        try:
            keys = await pool.kv_get_all(AppConst.PLUGINS)
            return {AppConst.PLUGINS: keys}
        except Exception as e:
            logger.error(f"Error listing plugins: {e}")
            return {"error": str(e)}

    @strawberry.input(
        name="DescribePluginInput",
        description="Describes plugin by name and optionally by revision")
    class DescribePlugin:
        plugin_name: str
        revision: str | None = strawberry.UNSET

    @strawberry.field
    async def describe_plugin(self, plugin_input: DescribePlugin) -> JSON:
        """
        Retrieves details of a plugin by plugin name.
        """
        pool = NatsConnectionPool.get_instance()

        if pool is None:
            raise ValueError("NatsPool is not initialized")
        try:
            if plugin_input.plugin_name:
                kv_payload = await pool.kv_get(AppConst.PLUGINS, plugin_input.plugin_name)
                return {AppConst.PLUGIN: kv_payload.decode()}
            else:
                return {"error": "Plugin name is required"}
        except Exception as e:
            logger.error(f"Error describing plugin {plugin_input.plugin_name}: {e}")
            return {"error": str(e)}


@strawberry.type
class Mutations(PlaybookMutations, PluginMutations):
    pass


@strawberry.type
class Queries(PlaybookQueries, PluginQueries):
    @strawberry.input(
        name="Instance",
        description="Shows events and commands, optionally by ID")
    class Instance:
        id: str | None = strawberry.UNSET

        def get_subject(self, subject_prefix: str, hierarchy_level: int = 1):
            if self.id not in [None, strawberry.UNSET, ""]:
                subject = f"{'.'.join([subject_prefix] + ['*'] * hierarchy_level + [self.id])}"
            else:
                subject = f"{subject_prefix}.>"
            logger.debug(subject)
            return subject

    @strawberry.field
    async def show_events(self, instance: Instance, info: Info) -> JSON:
        """
        Retrieves Events from NATS stream.
        """
        logger.debug(f"Info in show_events: {info}")

        return await read_nats_stream(
            stream=info.context.nats_event_stream,
            subject=instance.get_subject(subject_prefix=info.context.nats_event_prefix))

    @strawberry.field
    async def show_commands(self, instance: Instance, info: Info) -> JSON:
        """
        Retrieves Commands from NATS stream.
        """
        logger.debug(f"Info in show_commands: {info}")
        return await read_nats_stream(
            stream=info.context.nats_event_stream,
            subject=instance.get_subject(subject_prefix=info.context.nats_command_prefix))

    @strawberry.field
    async def show_all(self, instance: Instance, info: Info) -> JSON:
        """
        Retrieves Commands from NATS stream.
        """
        subject_prefix = info.context.nats_subscription_subject
        stream = info.context.nats_subscription_stream
        logger.debug(f"Show All subject_prefix: {subject_prefix}, stream: {stream} Info: {info}")
        return await read_nats_stream(
            stream=stream,
            subject=instance.get_subject(subject_prefix=subject_prefix, hierarchy_level=2))


async def read_nats_stream(stream: str, subject: str):
    """
    Retrieves Messages from NATS subject's stream.
    """
    messages = []

    async def message_handler(msg):
        msg_decoded = Payload.decode(msg.data)
        if msg_decoded:
            messages.append({AppConst.SUBJECT: msg.subject, AppConst.DATA: msg_decoded})

    nats_pool = NatsConnectionPool.get_instance()
    logger.debug(f"Pool instance in read_nats_stream: {nats_pool}")

    if nats_pool is None:
        raise ValueError("NatsPool is not initialized")

    try:
        async with nats_pool.connection() as js:
            consumer_name = f"{stream}-{uuid.uuid4()}"
            _ = await js.subscribe(
                subject=subject,
                durable=consumer_name,
                cb=message_handler,
                stream=stream
            )
            await asyncio.sleep(1)
            response_data = {stream: messages}
            logger.debug(response_data)
            return response_data

    except ErrTimeout:
        return {stream: 'read_nats_stream Timeout Error'}
    except Exception as e:
        return {stream: f"read_nats_stream Error {e}"}


schema = strawberry.Schema(query=Queries, mutation=Mutations)
