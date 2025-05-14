import pandas as pd
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from noetl.api.models.flow_transition import FlowTransition
from noetl.api.models.dict_component import DictComponent
from noetl.api.models.dict_operand import DictOperand

def generate_event_type(operand: str, component: str, next_state: str) -> str:
    return f"{component.capitalize()}{operand.capitalize()}{next_state.capitalize()}"

async def seed_flow_transition_csv(session: AsyncSession, folder_path: str) -> None:
    dict_component = pd.read_csv(f'{folder_path}/dict_component.csv').fillna('')
    dict_operand = pd.read_csv(f'{folder_path}/dict_operand.csv').fillna('')
    dict_state = pd.read_csv(f'{folder_path}/dict_state.csv').fillna('')
    dict_unit = pd.read_csv(f'{folder_path}/dict_unit.csv').fillna('')
    state_transition = pd.read_csv(f'{folder_path}/state_transition.csv').fillna('')
    unit_transition = pd.read_csv(f'{folder_path}/unit_transition.csv').fillna('')

    valid_units = pd.unique(unit_transition[['from_unit', 'to_unit']].values.ravel())
    existing = await session.exec(select(FlowTransition))
    existing_keys = {
        (t.operand_name, t.component_name, t.unit_name, t.current_state, t.event_type)
        for t in existing
    }

    new_transitions = []

    for _, operand_row in dict_operand.iterrows():
        operand_name = operand_row['operand_name']

        for _, component_row in dict_component.iterrows():
            component_name = component_row['component_name']
            route_path = f"/{component_name}/{operand_name}"

            for unit_name in valid_units:
                for _, state_row in state_transition.iterrows():
                    current_state = state_row['from_state']
                    next_state = state_row['to_state']

                    event_type = generate_event_type(operand_name, component_name, next_state)
                    key = (operand_name, component_name, unit_name, current_state, event_type)

                    if key not in existing_keys:
                        description = f"{operand_name.capitalize()} {component_name.capitalize()} for {unit_name} from {current_state} to {next_state}"

                        new_transitions.append(
                            FlowTransition(
                                operand_name=operand_name,
                                component_name=component_name,
                                unit_name=unit_name,
                                current_state=current_state,
                                next_state=next_state,
                                event_type=event_type,
                                route_path=route_path,
                                http_method="POST",
                                description=description
                            )
                        )

    session.add_all(new_transitions)
    await session.commit()
