from sqlmodel.ext.asyncio.session import AsyncSession
from noetl.config.settings import AppConfig
from noetl.api.models.seed.dict_component import seed_dict_component
from noetl.api.models.seed.dict_operand import seed_dict_operand
from noetl.api.models.seed.dict_resource import seed_dict_resource
from noetl.api.models.seed.dict_state import seed_dict_state
from noetl.api.models.seed.state_transition import seed_state_transition
from noetl.api.models.seed.dict_unit import seed_dict_unit
from noetl.api.models.seed.dict_operand import seed_dict_operand
from noetl.api.models.seed.dict_component import seed_dict_component
from noetl.api.models.seed.unit_transition import seed_unit_transition
from noetl.api.models.seed.dispatch import seed_dispatch

async def seed_all(session: AsyncSession, app_config: AppConfig) -> None:
    await seed_dict_resource(session)
    await seed_dict_state(session)
    await seed_state_transition(session)
    await seed_dict_unit(session)
    await seed_unit_transition(session)
    await seed_dict_operand(session)
    await seed_dict_component(session)
    await seed_dispatch(session, app_config.get_seed_folder())
