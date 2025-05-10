from sqlmodel import SQLModel
from noetl.api.models.dict_unit import DictUnit
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

def create_noetl_tables(engine):
    SQLModel.metadata.create_all(engine)

async def seed_dict_unit(session: AsyncSession) -> None:
    unit_definitions = {
        "workflow": "A runtime instance of a playbook, executed within a workload context.",
        "step": "A logical sequence of tasks or actions, with optional conditions and transitions.",
        "task": "A structural unit that groups related actions for modular execution.",
        "action": "An atomic unit that performs a single external operation.",
        "cursor": "A loop controller used for iterating over arrays or collections."
    }

    existing = await session.exec(select(DictUnit))
    current = {u.name for u in existing.all()}
    new_units = [DictUnit(name=name, description=desc) for name, desc in unit_definitions.items() if name not in current]
    session.add_all(new_units)
    await session.commit()