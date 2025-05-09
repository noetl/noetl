from sqlmodel.ext.asyncio.session import AsyncSession
from noetl.api.models.seed.dict_resource import seed_dict_resource
from noetl.api.models.seed.dict_state import seed_dict_state
from noetl.api.models.seed.state_transition import seed_state_transition

async def seed_all(session: AsyncSession) -> None:
    await seed_dict_resource(session)
    await seed_dict_state(session)
    await seed_state_transition(session)
