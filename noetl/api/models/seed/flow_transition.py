import re
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from noetl.api.models.flow_transition import FlowTransition
from noetl.api.models.dict_flow import DictFlow
from noetl.api.models.dict_unit import DictUnit

def route_path(event_type: str) -> list[str]:
    return [chunk.lower() for chunk in re.findall(r'[A-Z][a-z0-9]*', event_type)]

async def seed_flow_transitions(session: AsyncSession) -> None:
    default_start_state = "REQUESTED"

    flow_results = await session.exec(select(DictFlow))
    unit_results = await session.exec(select(DictUnit))
    flows = flow_results.all()
    units = unit_results.all()

    new_transitions = []
    existing = await session.exec(select(FlowTransition))
    existing_keys = {(ft.event_type, ft.event_state, ft.unit_name) for ft in existing.all()}

    for flow in flows:
        for unit in units:
            key = (flow.event_type, default_start_state, unit.name)
            if key not in existing_keys:
                new_transitions.append(FlowTransition(
                    event_type=flow.event_type,
                    event_state=default_start_state,
                    unit_name=unit.name,
                    route_path='/' + '/'.join(route_path(flow.event_type)),
                    http_method="POST",
                    module_name=route_path(flow.event_type)[0],
                    route_module=None,
                    service_module=None,
                    model_module=None,
                    table_name=None,
                    description=f"Transition for {flow.event_type} on {unit.name}",
                    next_event_type=None,
                    next_event_state=None
                ))

    session.add_all(new_transitions)
    await session.commit()
