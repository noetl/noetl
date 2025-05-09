from sqlmodel import SQLModel
from noetl.api.models.catalog import Catalog
from noetl.api.models.dict_resource import DictResource
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

def create_noetl_tables(engine):
    SQLModel.metadata.create_all(engine)


async def seed_dict_resource(session: AsyncSession) -> None:
    resource_names = [
        "Playbook",
        "Workflow",
        "Target",
        "Step",
        "Task",
        "Action",
    ]
    result = await session.exec(select(DictResource))
    existing = {r.name for r in result.all()}
    new_dict_resource = [
        DictResource(name=name)
        for name in resource_names
        if name not in existing
    ]
    session.add_all(new_dict_resource)
    await session.commit()