from typing import Optional
from loguru import logger

from src.components import BaseRepr
from src.components.models.meta import Metadata
from src.components.models.spec import Spec
from src.components.models.template import evaluate_template_input


class FiniteAutomata(BaseRepr):
    def __init__(self,
                 metadata: Metadata,
                 spec: Spec = Spec(),

                 ):
        super().__init__()

        self.metadata: Metadata = metadata
        self.spec: Spec = spec


    def set_state(self, new_state: str):

        if self.can_transition(new_state):
            self.state = new_state
        else:
            raise ValueError(f"Invalid state transition from {self.state} to {new_state}")

    def can_transition(self, new_state: str):

        if new_state in self.spec.transitions.get(self.spec.initial_state):
            return True
        else:
            return False

    def check_conditions(self):
        for condition in self.spec.conditions:
            template = evaluate_template_input(self, condition)
            logger.info(f"{self.metadata.name} condition {template}")
            if not eval(template):
                return False
        return True
