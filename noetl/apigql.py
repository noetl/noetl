import strawberry
import json
from loguru import logger
from natstream import get_nats_pool
from config import Config
from record import Record
from pydantic import BaseModel
import spacy
from strawberry.scalars import JSON

nlp = spacy.load("en_core_web_sm")


class InputValidationResult(BaseModel):
    is_valid: bool = False
    function_name: str | None = None
    message: str | None = None


class Input(BaseModel):
    tokens: str
    metadata: dict
    payload: dict


def validate_command(command_text):
    doc = nlp(command_text.lower())
    tokens = [token.text for token in doc]

    if not tokens:
        return False, None, None

    command_structures = {
        "add_workflow_config": ["add", "workflow", "config", str],
    }

    for function_name, structure in command_structures.items():
        if len(tokens) == len(structure):
            is_valid = all(t1 == t2 or isinstance(t2, type) and isinstance(t1, t2)
                           for t1, t2 in zip(tokens, structure))
            if is_valid:
                return InputValidationResult(is_valid=True, function_name=function_name,
                                             message=" ".join(tokens[len(structure):]))

    return InputValidationResult()


@strawberry.type
class ResponseMessage:
    message: JSON


@strawberry.type
class WorkflowResponse:
    identifier: str
    name: str
    event_type: str
    ack_seq: str
    status: str
    message: str


@strawberry.type
class WorkflowMutations:
    """
    GraphQL Mutations for NoETL Workflows.

    addWorkflowConfig Example:
    ```
    mutation {
      addWorkflowConfig(
        tokens: "add workflow config",
        metadata: "{ \"key\": \"value\" }",
        payload: {
          workflow_config_base64: "Base64 encoded string representing the YAML file"
        }
      ) {
            identifier
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
    async def add_workflow_config(self,
                                  payload: JSON,
                                  metadata: JSON | None = None,
                                  tokens: str | None = None,
                                  ) -> WorkflowResponse:
        logger.debug(f"tokens: {tokens}, metadata: {metadata}, payload: {payload}")
        pool = get_nats_pool()
        if pool is None:
            logger.error("NatsPoolContainer is not initialized")
            raise ValueError("NatsPoolContainer is not initialized")
        command_validation_result: InputValidationResult = validate_command(tokens)
        if command_validation_result.function_name == "add_workflow_config":
            try:
                logger.debug(type(payload))
                workflow_config = Config.create_workflow(payload)
                workflow_name = workflow_config.get_value("metadata.name")
                event_type = "WorkflowConfigRegistrationRequested"
                logger.info(workflow_config)
                record = Record.create(
                    name=workflow_name,
                    metadata=metadata | {"event_type": event_type} if metadata else {"event_type": event_type},
                    reference=None,
                    payload=workflow_config
                )

                ack = await pool.publish(
                    subject=f"event.RegistrationRequested.{record.identifier}",
                    message=record.serialize()
                )
                logger.info(f"Ack: stream={ack.stream}, sequence={ack.seq}, Identifier={record.identifier}")
                return WorkflowResponse(
                    identifier=record.identifier,
                    name=workflow_name,
                    event_type=event_type,
                    ack_seq=ack.seq,
                    status="WorkflowConfigRegistrationRequested",
                    message="Workflow config has been successfully requested for addition"
                )

            except Exception as e:
                logger.error(f"Request failed due to error: {str(e)}")
                raise ValueError(f"Request failed due to error: {str(e)}")
        else:
            logger.error(f"Request IS NOT added {tokens}")
            raise ValueError(f"Request IS NOT added {tokens}")

    @strawberry.mutation
    async def delete_workflow_config(self, workflow_id: str) -> str:
        pass


@strawberry.type
class WorkflowQueries:
    @strawberry.field
    async def get_workflow_config(self, workflow_id: str) -> str:
        pass


# plugin


@strawberry.type
class PluginMutations:
    @strawberry.mutation
    async def add_plugin(self, plugin_data: JSON) -> str:
        pass

    @strawberry.mutation
    async def delete_plugin(self, plugin_id: str) -> str:
        pass


@strawberry.type
class PluginQueries:
    @strawberry.field
    async def get_plugin(self, plugin_id: str) -> str:
        pass


# schema
@strawberry.type
class Mutations(WorkflowMutations, PluginMutations):
    pass


@strawberry.type
class Queries(WorkflowQueries, PluginQueries):
    pass


schema = strawberry.Schema(query=Queries, mutation=Mutations)
