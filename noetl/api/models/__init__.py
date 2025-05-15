from noetl.api.models.catalog import Catalog
from noetl.api.models.dict_resource import DictResource
from noetl.api.models.context import Context
from noetl.api.models.event import Event
from noetl.api.models.dict_state import DictState
from noetl.api.models.dict_operand import DictOperand
from noetl.api.models.flow_transition import FlowTransition
from noetl.api.models.seed.dict_component import DictComponent
from noetl.api.models.runtime import Runtime
from noetl.api.models.workload import Workload
from noetl.api.models.result import Result
from noetl.api.models.state_transition import StateTransition
from noetl.api.models.dict_unit import DictUnit
from noetl.api.models.unit_transition import UnitTransition
from noetl.api.models.dispatch import Dispatch

__all__ = [
    "Catalog",
    "DictResource",
    "Context",
    "Event",
    "DictState",
    "DictOperand",
    "DictComponent",
    "FlowTransition",
    "StateTransition",
    "Runtime",
    "Workload",
    "Result",
    "DictUnit",
    "UnitTransition",
]


def create_noetl_tables(engine):
    from sqlmodel import SQLModel
    SQLModel.metadata.create_all(engine)