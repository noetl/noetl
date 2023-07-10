import strawberry
import json
from typing import List, Optional, Dict
from src.storage import db


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
class HttpRequest:
    description: Optional[str]
    type: str
    method: str
    url: str
    headers: Optional[Dict[str, str]]
    requestBody: Optional[str]


@strawberry.type
class Step:
    command: Optional[Command]
    httpRequest: Optional[HttpRequest]


@strawberry.type
class Task:
    steps: Step


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
class Spec:
    vars: Dict[str, str]
    timeout: int
    schedule: Optional[str]
    initialSettings: InitialSettings
    transitions: Transition
    tasks: Dict[str, Task]


@strawberry.type
class Workflow:
    apiVersion: str
    kind: str
    metadata: Metadata
    spec: Spec


@strawberry.type
class Query:
    @strawberry.field
    def get_workflow(self, name: str) -> Optional[Workflow]:
        workflow_json = await db.load(f'workflow:{name}')
        if workflow_json is None:
            return None
        else:
            return json.loads(workflow_json)


@strawberry.type
class Mutation:
    @strawberry.mutation
    def submit_workflow(self, workflow: Workflow) -> bool:
        workflow_json = json.dumps(workflow)
        await db.save(f'workflow:{workflow.metadata.name}', workflow_json)
        return True


schema = strawberry.Schema(query=Query, mutation=Mutation)
