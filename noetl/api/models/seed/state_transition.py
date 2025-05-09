from sqlmodel import SQLModel
from noetl.api.models.state_transition import StateTransition
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

def create_noetl_tables(engine):
    SQLModel.metadata.create_all(engine)


async def seed_state_transition(session: AsyncSession) -> None:

    transition_matrix = {
        "REQUESTED":  {"REGISTERED": True,  "CANCELED": True},
        "REGISTERED": {"STARTED":    True,  "CANCELED": True},
        "STARTED":    {"FAILED":     True,  "COMPLETED": True, "TERMINATED": True, "PAUSED": True},
        "CANCELED":   {},
        "FAILED":     {"RESTARTED": True},
        "COMPLETED":  {},
        "TERMINATED": {"RESTARTED": True},
        "PAUSED":     {"COMPLETED": True, "TERMINATED": True, "CONTINUED": True},
        "CONTINUED":  {"FAILED": True, "COMPLETED": True, "TERMINATED": True, "PAUSED": True},
        "RESTARTED":  {"FAILED": True, "COMPLETED": True, "TERMINATED": True, "PAUSED": True, "CONTINUED": True},
    }

    result = await session.exec(select(StateTransition))
    existing = {(t.from_state, t.to_state) for t in result.all()}

    new_transitions = []
    for frm, targets in transition_matrix.items():
        for to, allowed in targets.items():
            if allowed and (frm, to) not in existing:
                new_transitions.append(
                    StateTransition(from_state=frm, to_state=to, active=True)
                )
    session.add_all(new_transitions)
    await session.commit()