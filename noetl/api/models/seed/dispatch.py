import pandas as pd
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from noetl.api.models.dispatch import Dispatch
from noetl.api.models.dict_component import DictComponent
from noetl.api.models.dict_operand import DictOperand

def generate_event_type(operand: str, component: str, state: str) -> str:
    return f"{component.capitalize()}{operand.capitalize()}{state.capitalize()}"

async def seed_dispatch(session: AsyncSession, folder_path: str) -> None:
    dict_component = pd.read_csv(f'{folder_path}/dict_component.csv').fillna('')
    dict_operand = pd.read_csv(f'{folder_path}/dict_operand.csv').fillna('')
    dict_state = pd.read_csv(f'{folder_path}/dict_state.csv').fillna('')
    dict_unit = pd.read_csv(f'{folder_path}/dict_unit.csv').fillna('')
    unit_transition = pd.read_csv(f'{folder_path}/unit_transition.csv').fillna('')

    valid_units = pd.unique(unit_transition[['from_unit', 'to_unit']].values.ravel())
    existing = await session.exec(select(Dispatch))
    existing_keys = {
        (t.operand_name, t.component_name, t.unit_name, t.state, t.event_type)
        for t in existing
    }

    new_dispatch_entries = []

    for _, operand_row in dict_operand.iterrows():
        operand_name = operand_row['operand_name']

        for _, component_row in dict_component.iterrows():
            component_name = component_row['component_name']
            route_path = f"/{component_name}/{operand_name}"

            for unit_name in valid_units:
                for _, state_row in dict_state.iterrows():
                    state = state_row['name']
                    event_type = generate_event_type(operand_name, component_name, state)
                    key = (operand_name, component_name, unit_name, state, event_type)

                    if key not in existing_keys:
                        description = f"{operand_name.capitalize()} {component_name.capitalize()} for {unit_name} in state {state}"

                        new_dispatch_entries.append(
                            Dispatch(
                                operand_name=operand_name,
                                component_name=component_name,
                                unit_name=unit_name,
                                state=state,
                                event_type=event_type,
                                route_path=route_path,
                                http_method="POST",
                                description=description
                            )
                        )

    session.add_all(new_dispatch_entries)
    await session.commit()