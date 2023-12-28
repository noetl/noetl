import uuid
import asyncio
import strawberry
from loguru import logger
from pydantic import BaseModel
import spacy
from strawberry.scalars import JSON
from strawberry.types import Info
from payload import Payload, NatsConnectionPool, ErrTimeout, PubAck, AppKey, Metadata, Reference, EventType, CommandType


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
    payload: dict


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


# @strawberry.type
# class Reference:
#     timestamp: str
#     identifier: str
#     reference: str
#     origin: str
#     subject: str
#     stream: str
#     seq: str
#     playbook: str | None = None
#     task: str | None = None
#     step: str | None = None
#     domain: str | None = None
#     duplicate: str | None = None


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
            "event_type": self.event_type,
            "status": self.status,
            "message": self.message}


@strawberry.type
class PlaybookMutations:
    """
    GraphQL Mutations for NoETL Playbooks.

    registerPlaybook Example:
    ```
    mutation {
      registerPlaybook(
        tokens: "register Playbook",
        metadata: {"source": "noetl-cli", "handler": "register_Playbook"},
        Playbook_base64: "Base64 encoded string of Playbook template YAML"
      ) {
            reference
            name
            eventType
            status
            message
      }
    }
    ```
    """

    @strawberry.mutation
    async def register_playbook(self,
                                playbook_base64: str,
                                info: Info,
                                metadata: JSON | None = strawberry.UNSET,
                                tokens: str | None = strawberry.UNSET,
                                ) -> RegistrationResponse:
        logger.debug(f"{AppKey.TOKENS}: {tokens}, {AppKey.METADATA}: {metadata}, {AppKey.PLAYBOOK_BASE64}: {playbook_base64}")
        pool = NatsConnectionPool.get_instance()
        if pool is None:
            raise ValueError("NatsPool is not initialized")
        command_validation_result: InputValidationResult = validate_command(tokens)
        if command_validation_result.function_name == "register_playbook":
            try:
                event_type = EventType.PLAYBOOK_REGISTRATION_REQUESTED
                playbook_name = Payload.base64_yaml(playbook_base64).get(AppKey.METADATA).get(AppKey.NAME)
                if playbook_name is None:
                    raise ValueError("playbook name is missing in the YAML.")
                nats_payload = Payload.create(
                    payload_data={
                        AppKey.PLAYBOOK_NAME: playbook_name,
                        AppKey.PLAYBOOK_BASE64: playbook_base64,
                        AppKey.METADATA: metadata | {
                            AppKey.PLAYBOOK_NAME: playbook_name,
                            AppKey.TOKENS: tokens
                        }
                    },
                    event_type=event_type,
                    nats_pool=pool
                )
                subject=f"{info.context.nats_event_prefix}.{AppKey.DISPATCHER}.{nats_payload.get_origin_id()}"
                nats_payload.set_value(Reference.SUBJECT, subject)
                ack: PubAck = await nats_payload.event_write(
                    subject=subject,
                    stream=info.context.nats_event_stream,
                    message=nats_payload.encode()
                )
                registration_response = RegistrationResponse(
                    reference=nats_payload.get_api_reference() | ack.as_dict(),
                    kind="Playbook",
                    name=nats_payload.get_value(AppKey.PLAYBOOK_NAME),
                    event_type=nats_payload.get_value(Metadata.EVENT_TYPE),
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
            keys = await pool.kv_get_all(AppKey.PLAYBOOKS)
            return {AppKey.PLAYBOOKS: keys}
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
    async def describe_playbook(self, playbook_input: DescribePlaybook)  -> JSON:
        """
        Retrieves details of a playbook by playbook name.
        """
        pool = NatsConnectionPool.get_instance()
        try:
            if playbook_input.playbook_name:
                value = await pool.kv_get(AppKey.PLAYBOOKS, playbook_input.playbook_name)
                return {AppKey.PLAYBOOK: Payload.decode(value)}
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
            event_type = EventType.PLAYBOOK_EXECUTION_REQUESTED
            metadata = run_playbook_input.metadata if run_playbook_input.metadata is not strawberry.UNSET else {}
            revision = {AppKey.REVISION_NUMBER: run_playbook_input.revision} or {}
            nats_payload = Payload.create(
                payload_data={AppKey.PLAYBOOK_NAME: run_playbook_input.playbook_name},
                event_type=event_type,
                nats_pool=pool
            )
            if run_playbook_input.input is not strawberry.UNSET:
                nats_payload.set_value(AppKey.PLAYBOOK_INPUT, run_playbook_input.input)
            if run_playbook_input.metadata is not strawberry.UNSET:
                nats_payload.set_value(AppKey.METADATA,
                                       nats_payload.get_value(AppKey.METADATA) | run_playbook_input.metadata)
            if run_playbook_input.tokens is not strawberry.UNSET:
                nats_payload.set_value(Metadata.TOKENS, run_playbook_input.tokens)
            if run_playbook_input.revision is not strawberry.UNSET:
                nats_payload.set_value(Metadata.REVISION_NUMBER, run_playbook_input.revision)

            subject = f"{info.context.nats_event_prefix}.{AppKey.DISPATCHER}.{nats_payload.get_origin_id()}"
            nats_payload.set_value(Reference.SUBJECT, subject)
            ack: PubAck = await nats_payload.event_write(
                subject=subject,
                stream=info.context.nats_event_stream,
                message=nats_payload.encode()
            )
            registration_response = RegistrationResponse(
                reference = nats_payload.get_api_reference() | ack.as_dict(),
                kind="Playbook",
                name=nats_payload.get_value(AppKey.PLAYBOOK_NAME),
                event_type=nats_payload.get_value(Metadata.EVENT_TYPE),
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

        logger.debug(f"{AppKey.PLUGIN_NAME}: {registration_input.plugin_name}, "
                     f"{AppKey.IMAGE_URL}: {registration_input.image_url}, {AppKey.METADATA}: {registration_input.metadata}")
        pool = NatsConnectionPool.get_instance()
        if pool is None:
            raise ValueError("NatsPool is not initialized")
        command_validation_result: InputValidationResult = validate_command(registration_input.tokens)
        if command_validation_result.function_name == "register_plugin":
            try:
                event_type = EventType.PLUGIN_REGISTRATION_REQUESTED
                if registration_input.plugin_name is None:
                    raise ValueError("Plugin name is missing.")
                if registration_input.image_url is None:
                    raise ValueError("Plugin image url is missing.")
                nats_payload = Payload.create(
                    payload_data={
                        AppKey.PLUGIN_NAME: registration_input.plugin_name,
                        AppKey.IMAGE_URL: registration_input.image_url,
                    },
                    event_type=event_type,
                    nats_pool=pool
                )
                if registration_input.metadata is not strawberry.UNSET:
                    nats_payload.set_value(AppKey.METADATA, nats_payload.get_value(AppKey.METADATA) | registration_input.metadata)
                if registration_input.tokens is not strawberry.UNSET:
                    nats_payload.set_value(Metadata.TOKENS, registration_input.tokens)

                subject=f"{info.context.nats_event_prefix}.{AppKey.DISPATCHER}.{nats_payload.get_origin_id()}"
                nats_payload.set_value(Reference.SUBJECT, subject)
                ack: PubAck = await nats_payload.event_write(
                    subject=subject,
                    stream=info.context.nats_event_stream,
                    message=nats_payload.encode()
                )
                reference = nats_payload.get_api_reference() | ack.as_dict(),
                registration_response = RegistrationResponse(
                    reference=reference,
                    kind="Plugin",
                    name=nats_payload.get_value(AppKey.PLUGIN_NAME),
                    event_type=nats_payload.get_value(Metadata.EVENT_TYPE),
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
            keys = await pool.kv_get_all(AppKey.PLUGINS)
            return {AppKey.PLUGINS: keys}
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
        try:
            if plugin_input.plugin_name:
                value = await pool.kv_get(AppKey.PLUGINS, plugin_input.plugin_name)
                return {AppKey.PLUGIN: Payload.decode(value)}
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

    @strawberry.field
    async def show_events(self, info: Info) -> JSON:
        """
        Retrieves messages from the Events NATS stream.
        """
        logger.debug(f"Self in show_events: {self}")
        stream = info.context.nats_event_stream,
        return await read_nats_stream(
            stream=info.context.nats_event_stream,
            subject=f"{info.context.nats_event_prefix}.>")

    @strawberry.field
    async def show_commands(self, info: Info) -> JSON:
        """
        Retrieves messages from the Commands NATS stream.
        """
        logger.debug(f"Self in show_commands: {self}")
        return await read_nats_stream(
            stream=info.context.nats_command_stream,
            subject=f"{info.context.nats_command_prefix}.>")


async def read_nats_stream(stream: str, subject: str):
    messages = []

    async def message_handler(msg):
        msg_decoded = Payload.decode(msg.data)
        if msg_decoded:
            messages.append({AppKey.SUBJECT: msg.subject, AppKey.DATA: msg_decoded})

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
            logger.info(response_data)
            return response_data

    except ErrTimeout:
        return {stream: 'read_nats_stream Timeout Error'}
    except Exception as e:
        return {stream: f"read_nats_stream Error {e}"}


schema = strawberry.Schema(query=Queries, mutation=Mutations)
