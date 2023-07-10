import json

import strawberry
from typing import List, Optional
from storage import db


def strawberry_model(cls):
    cls_input = strawberry.input(cls)
    cls_type = strawberry.type(cls)
    cls.__annotations__ = cls_type.__annotations__
    cls = cls_input(cls)
    return cls


@strawberry.type
class Metadata:
    name: str


@strawberry.type
class Command:
    description: Optional[str]
    type: str
    command: str
    args: List[str]


@strawberry.type
class Header:
    key: str
    value: str


@strawberry.type
class HttpRequest:
    description: Optional[str]
    type: str
    method: str
    url: str
    headers: Optional[List[Header]]
    requestBody: Optional[str]


@strawberry.type
class Step:
    command: Optional[Command]
    httpRequest: Optional[HttpRequest]


@strawberry.type
class Task:
    steps: Step


@strawberry.type
class TaskEntry:
    key: str
    task: Task


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
    vars: Optional[List[Variable]]
    timeout: int
    schedule: Optional[str]
    initialSettings: InitialSettings
    transitions: Transition
    tasks: Optional[List[TaskEntry]]


@strawberry.type
class Workflow:
    apiVersion: str
    kind: str
    metadata: Metadata
    spec: Spec
    def __init__(self, apiVersion: str, kind: str, metadata: Metadata, spec: Spec):
        self.apiVersion = apiVersion
        self.kind = kind
        self.metadata = metadata
        self.spec = spec



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
class Mutation:
    @strawberry.mutation
    async def submit_workflow(self, workflow: Workflow) -> bool:
        workflow_json = json.dumps(workflow)
        await db.save(f'workflow:{workflow.metadata.name}', workflow_json)
        return True


schema = strawberry.Schema(query=Query)
