from sqlmodel import SQLModel
from noetl.api.models.unit_transition import UnitTransition
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

def create_noetl_tables(engine):
    SQLModel.metadata.create_all(engine)


async def seed_unit_transition(session: AsyncSession) -> None:
    transitions = [
        ("workflow", "step", "RUN"),
        ("step", "workflow", "RUN"),
        ("step", "task", "RUN"),
        ("step", "action", "RUN"),
        ("step", "step", "NEXT"),
        ("task", "action", "RUN"),
        ("cursor", "step", "RUN"),
        ("cursor", "action", "RUN"),
    ]

    existing = await session.exec(select(UnitTransition))
    current = {(t.from_unit, t.to_unit, t.method) for t in existing.all()}

    new_transitions = [
        UnitTransition(from_unit=src, to_unit=dst, method=label, active=True)
        for src, dst, label in transitions if (src, dst, label) not in current
    ]
    session.add_all(new_transitions)
    await session.commit()