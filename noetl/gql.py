import strawberry
from loguru import logger
from natstream import NatsConnectionPool
from pydantic import BaseModel
import spacy
from strawberry.scalars import JSON
from payload import Payload


class Command:
    class Tokenizer:
        def __init__(self):
            self.nlp = spacy.load("en_core_web_sm")

        def get_tokens(self, command_text):
            doc = self.nlp(command_text.lower())
            return [token.text for token in doc]

    class Structures:
        command_structures = {
            "register_workflow": ["register", "workflow", str],
            "run_workflow": ["run", "workflow", str],
            "describe_workflow": ["describe", "workflow", str],
            "show_workflow": ["show", "workflow", str],
            "status_workflow": ["status", "workflow", str],
            "append_data_to_workflow": ["append", "data", "to", "workflow", str],
            "kill_workflow": ["kill", "workflow", str],
            "unregister_workflow": ["drop", "workflow", str],
            "list_workflows": ["list", "workflows"],
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


@strawberry.type
class ReferenceIdentifierType:
    timestamp: str
    identifier: str
    reference: str
    origin: str

@strawberry.type
class RegistrationResponse:
    reference_identifier: ReferenceIdentifierType | None = None
    kind: str | None = None
    name: str | None = None
    event_type: str | None = None
    ack_seq: str | None = None
    status: str | None = None
    message: str | None = None

    def to_dict(self):
        return {
            "reference_identifier": self.reference_identifier,
            "kind": self.kind,
            "name": self.name,
            "event_type": self.event_type,
            "ack_seq": self.ack_seq,
            "status": self.status,
            "message": self.message}


@strawberry.type
class WorkflowMutations:
    """
    GraphQL Mutations for NoETL Workflows.

    registerWorkflow Example:
    ```
    mutation {
      registerWorkflow(
        tokens: "register workflow",
        metadata: {"source": "noetl-cli", "handler": "register_workflow"},
        workflow_base64: "Base64 encoded string of workflow template YAML"
      ) {
            referenceIdentifier {
                timestamp
                identifier
                reference
                origin
            }
            name
            eventType
            ackSeq
            status
            message
      }
    }
    ```
    """

    @strawberry.mutation
    async def register_workflow(self,
                                workflow_base64: str,
                                metadata: JSON | None = None,
                                tokens: str | None = None,
                                ) -> RegistrationResponse:
        logger.debug(f"tokens: {tokens}, metadata: {metadata}, workflow_base64: {workflow_base64}")
        pool = NatsConnectionPool.get_instance()
        if pool is None:
            raise ValueError("NatsPool is not initialized")
        command_validation_result: InputValidationResult = validate_command(tokens)
        if command_validation_result.function_name == "register_workflow":
            try:
                event_type = "WorkflowRegistrationRequested"
                workflow_name = Payload.base64_yaml(workflow_base64).get("metadata").get("name")
                if workflow_name is None:
                    raise ValueError("Workflow name is missing in the YAML.")
                nats_payload = Payload.create(
                    payload_data={
                        "workflow_name": workflow_name,
                        "workflow_base64": workflow_base64,
                        "metadata": metadata | {
                            "workflow_name": workflow_name,
                            "tokens": tokens
                        }
                    },
                    event_type=event_type,
                    nats_pool=pool
                )
                ack = await nats_payload.event_write(
                    subject=f"dispatcher.{nats_payload.get_subject_ref()}",
                    message=nats_payload.encode()
                )
                registration_response = RegistrationResponse(
                    reference_identifier=ReferenceIdentifierType(**nats_payload.get_ref()),
                    kind="Workflow",
                    name=nats_payload.get_value("workflow_name"),
                    event_type=nats_payload.get_value("metadata.event_type"),
                    ack_seq=ack.seq,
                    status="WorkflowRegistrationRequested",
                    message="Workflow registration has been successfully requested"
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
    async def delete_workflow(self, workflow_id: str) -> str:
        pass


@strawberry.type
class WorkflowQueries:
    @strawberry.field
    async def list_workflows(self) -> JSON:
        """
        Retrieves list all workflows in the NATS KV store.
        """
        pool = NatsConnectionPool.get_instance()
        try:
            keys = await pool.kv_get_all("workflows")
            return {"workflows": keys}
        except Exception as e:
            logger.error(f"Error listing workflows: {e}")
            return {"error": str(e)}

    @strawberry.field
    async def describe_workflow(self, workflow_name: str, revision: str = None) -> JSON:
        """
        Retrieves details of a workflow by workflow name.
        """
        pool = NatsConnectionPool.get_instance()
        try:
            if workflow_name:
                value = await pool.kv_get("workflows", workflow_name)
                return {"workflow": Payload.decode(value).yaml_value()}
            else:
                return {"error": "Workflow name is required"}
        except Exception as e:
            logger.error(f"Error describing workflow {workflow_name}: {e}")
            return {"error": str(e)}

    @strawberry.field
    async def run_workflow(
            self,
            workflow_name: str,
            metadata: JSON | None = None,
            workflow_input: JSON = None,
            tokens: str | None = None,
            revision: str = None
    ) -> RegistrationResponse:
        """
        Requests to execute a workflow by workflow name.
        """
        pool = NatsConnectionPool.get_instance()
        if pool is None:
            raise ValueError("NatsPool is not initialized")
        try:
            event_type = "WorkflowExecutionRequested"
            metadata = metadata or {}
            revision = {"revision": revision} or {}
            workflow_input = {workflow_input: workflow_input} if workflow_input else {}
            nats_payload = Payload.create(
                payload_data={
                    "workflow_name": workflow_name,
                    "workflow_input": workflow_input,
                    "metadata": metadata | {
                        "workflow_name": workflow_name,
                        "tokens": tokens
                    }
                },
                event_type=event_type,
                nats_pool=pool
            )
            ack = await nats_payload.event_write(
                subject=f"dispatcher.{nats_payload.get_subject_ref()}",
                message=nats_payload.encode()
            )
            registration_response = RegistrationResponse(
                reference_identifier=ReferenceIdentifierType(**nats_payload.get_ref()),
                kind="RunWorkflow",
                name=nats_payload.get_value("workflow_name"),
                event_type=nats_payload.get_value("metadata.event_type"),
                ack_seq=ack.seq,
                status="WorkflowExecutionRequested",
                message="Workflow execution has been successfully requested"
            )
            logger.info(f"Ack: {registration_response}")
            return registration_response

        except Exception as e:
            logger.error(f"Request failed due to error: {str(e)}")
            raise ValueError(f"Request failed due to error: {str(e)}")


@strawberry.type
class PluginMutations:
    @strawberry.mutation
    async def register_plugin(self, plugin_name: str, image_url: str, metadata: JSON | None = None,
                              tokens: str | None = None) -> RegistrationResponse:

        logger.debug(f"plugin_name: {plugin_name}, image_url: {image_url}, metadata: {metadata}")
        pool = NatsConnectionPool.get_instance()
        if pool is None:
            raise ValueError("NatsPool is not initialized")
        command_validation_result: InputValidationResult = validate_command(tokens)
        if command_validation_result.function_name == "register_plugin":
            try:
                event_type = "PluginRegistrationRequested"
                if plugin_name is None:
                    raise ValueError("Plugin name is missing.")
                if image_url is None:
                    raise ValueError("Plugin image url is missing.")
                nats_payload = Payload.create(
                    payload_data={"plugin_name": plugin_name, "image_url": image_url, "metadata": metadata},
                    event_type=event_type,
                    nats_pool = pool
                )

                ack = await nats_payload.event_write(
                    subject=f"dispatcher.{nats_payload.get_subject_ref()}",
                    message=nats_payload.encode()
                )
                registration_response = RegistrationResponse(
                    reference_identifier=ReferenceIdentifierType(**nats_payload.get_ref()),
                    kind="Plugin",
                    name=nats_payload.get_value("plugin_name"),
                    event_type=nats_payload.get_value("metadata.event_type"),
                    ack_seq=ack.seq,
                    status="PluginRegistrationRequested",
                    message="Plugin registration has been successfully requested"
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
            keys = await pool.kv_get_all("plugins")
            return {"plugins": keys}
        except Exception as e:
            logger.error(f"Error listing plugins: {e}")
            return {"error": str(e)}

    @strawberry.field
    async def describe_plugin(self, plugin_name: str, revision: str = None) -> JSON:
        """
        Retrieves details of a plugin by plugin name.
        """
        pool = NatsConnectionPool.get_instance()
        try:
            if plugin_name:
                value = await pool.kv_get("plugins", plugin_name)
                return {"plugin": Payload.decode(value)}
            else:
                return {"error": "Plugin name is required"}
        except Exception as e:
            logger.error(f"Error describing plugin {plugin_name}: {e}")
            return {"error": str(e)}


@strawberry.type
class EventCommandMutations:
    @strawberry.mutation
    async def delete_events(self) -> ResponseMessage:
        try:
            pool = NatsConnectionPool.get_instance()
            await pool.truncate_stream("events")
            return ResponseMessage(message="Events deleted successfully.")
        except Exception as e:
            logger.error(f"Failed to delete events: {str(e)}")
            return ResponseMessage(message=f"Error: {str(e)}")

    @strawberry.mutation
    async def delete_commands(self) -> ResponseMessage:
        try:
            pool = NatsConnectionPool.get_instance()
            await pool.truncate_stream("commands")
            return ResponseMessage(message="Commands deleted successfully.")
        except Exception as e:
            logger.error(f"Failed to delete commands: {str(e)}")
            return ResponseMessage(message=f"Error: {str(e)}")


@strawberry.type
class Mutations(WorkflowMutations, PluginMutations, EventCommandMutations):
    pass


@strawberry.type
class Queries(WorkflowQueries, PluginQueries):
    pass


schema = strawberry.Schema(query=Queries, mutation=Mutations)
