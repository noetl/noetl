from sqlmodel import SQLModel
from noetl.api.models.catalog import Catalog
from noetl.api.models.dict_resource import DictResource
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

def create_noetl_tables(engine):
    SQLModel.metadata.create_all(engine)


async def seed_dict_resource(session: AsyncSession) -> None:
    resources_with_descriptions = {
        "Playbook": "A versioned declarative file defining rules, tasks, and actions for execution.",
        "Workflow": "The runtime execution of a Playbook, composed of steps and transitions.",
        "Step": "A logical control block in a Workflow that defines sequencing and conditions.",
        "Task": "An container unit of action group.",
        "Action": "An atomic executable unit, often interfacing with APIs or databases.",
        "Target": "A runtime scope or destination for workflow execution (e.g., environment, system).",
        "Endpoint": "An external API or internal service URL invoked by Actions or Tasks.",
        "Model": "An AI/ML model used within workflows.",
        "Dataset": "A structured collection of data used for training, testing, or inference.",
        "Connector": "An integration interface to external systems (e.g., database, API, queue).",
        "Trigger": "An event or condition that initiates a Playbook or Workflow execution."
    }

    result = await session.exec(select(DictResource))
    existing = {r.name for r in result.all()}

    new_dict_resources = [
        DictResource(name=name, description=description)
        for name, description in resources_with_descriptions.items()
        if name not in existing
    ]

    session.add_all(new_dict_resources)
    await session.commit()