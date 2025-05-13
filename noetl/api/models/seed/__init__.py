from sqlmodel.ext.asyncio.session import AsyncSession
from noetl.api.models.seed.dict_resource import seed_dict_resource
from noetl.api.models.seed.dict_state import seed_dict_state
from noetl.api.models.seed.dict_flow import seed_dict_flow
from noetl.api.models.seed.state_transition import seed_state_transition
from noetl.api.models.seed.dict_unit import seed_dict_unit
from noetl.api.models.seed.unit_transition import seed_unit_transition
from noetl.api.models.seed.flow_transition import seed_flow_transitions


async def seed_all(session: AsyncSession) -> None:
    await seed_dict_resource(session)
    await seed_dict_state(session)
    await seed_state_transition(session)
    await seed_dict_unit(session)
    await seed_unit_transition(session)
    await seed_dict_flow(session)
    await seed_flow_transitions(session)
