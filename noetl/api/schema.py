import strawberry
import json
from loguru import logger
from typing import List, Optional
from common import db
from common import to_dict


@strawberry.type
class Metadata:
    name: str


@strawberry.type
class Command:
    description: None | str
    type: str
    command: str
    args: List[str]


@strawberry.type
class Header:
    key: str
    value: str


@strawberry.type
class HttpRequest:
    description: None | str
    type: str
    method: str
    url: str
    headers: None | List[Header]
    requestBody: None | str


@strawberry.type
class Step:
    command: None | Command
    httpRequest: None | HttpRequest


@strawberry.type
class Task:
    steps: None | Step


@strawberry.type
class TaskEntry:
    key: str
    task: None | Task


@strawberry.type
class InitialSettings:
    start: List[str]
    state: str


@strawberry.type
class Transition:
    ready: List[str]
    running: List[str]
    idle: List[str]
    paused: List[str]


@strawberry.type
class Variable:
    key: str
    value: str


@strawberry.type
class Spec:
    vars: None | List[Variable]
    timeout: None | int
    schedule: None | str
    initialSettings: InitialSettings
    transitions: Transition
    tasks: None | List[TaskEntry]


@strawberry.type
class Workflow:
    apiVersion: str
    kind: str
    metadata: Metadata
    spec: Spec


@strawberry.type
class Query:
    @strawberry.field
    async def get_workflow(self, name: str) -> Optional[Workflow]:
        workflow_json = await db.load(f'workflow:{name}')
        if workflow_json is None:
            return None
        else:
            workflow_data = json.loads(workflow_json)
            return Workflow(**workflow_data)


@strawberry.input
class MetadataInput:
    name: str


@strawberry.input
class CommandInput:
    description: None | str = strawberry.field(default_factory=lambda: strawberry.UNSET)
    type: str
    command: str
    args: List[str]


@strawberry.input
class HeaderInput:
    key: str
    value: str


@strawberry.input
class HttpRequestInput:
    description: None | str = strawberry.field(default_factory=lambda: strawberry.UNSET)
    type: str
    method: str
    url: str
    headers: None | List[HeaderInput] = strawberry.field(default_factory=lambda: strawberry.UNSET)
    requestBody: None | str = strawberry.field(default_factory=lambda: strawberry.UNSET)


@strawberry.input
class StepInput:
    command: None | CommandInput = strawberry.field(default_factory=lambda: strawberry.UNSET)
    httpRequest: None | HttpRequestInput = strawberry.field(default_factory=lambda: strawberry.UNSET)


@strawberry.input
class TaskInput:
    steps: List[StepInput]


@strawberry.input
class TaskEntryInput:
    key: str
    task: TaskInput


@strawberry.input
class InitialSettingsInput:
    start: List[str]
    state: str


@strawberry.input
class TransitionInput:
    ready: List[str]
    running: List[str]
    idle: List[str]
    paused: List[str]


@strawberry.input
class VariableInput:
    key: str
    value: str


@strawberry.input
class SpecInput:
    vars: List[VariableInput] = strawberry.field(default_factory=list)
    timeout: int = 30
    schedule: None | str = strawberry.field(default_factory=lambda: strawberry.UNSET)
    initialSettings: InitialSettingsInput
    transitions: TransitionInput
    tasks: None | List[TaskEntryInput] = strawberry.field(default_factory=lambda: strawberry.UNSET)


@strawberry.input
class WorkflowInput:
    apiVersion: str
    kind: str
    metadata: MetadataInput
    spec: SpecInput


@strawberry.type
class Mutation:

    @strawberry.mutation
    async def submit_workflow(self, workflow: WorkflowInput) -> bool:
        logger.info(workflow)

        workflow_dict = to_dict(workflow)
        logger.info(workflow_dict)
        await db.save(f'workflow:{workflow.metadata.name}', json.dumps(workflow_dict))
        return True


schema = strawberry.Schema(query=Query, mutation=Mutation)
