from typing import Optional
from noetl.ncl.common import BaseRepr
from noetl.ncl.config import evaluate_template_input


class FiniteAutomata(BaseRepr):
    def __init__(self,
                 initial_state: str,
                 transitions: Optional[dict[str, list[str]]],
                 conditions: Optional[list[str]] = None
                 ):
        super().__init__()

        self.state = initial_state
        self.transitions = transitions
        self.conditions: Optional[list[str]] = conditions

    def set_state(self, new_state: str):

        if self.can_transition(new_state):
            self.state = new_state
        else:
            raise ValueError(f"Invalid state transition from {self.state} to {new_state}")

    def can_transition(self, new_state: str):

        if new_state in self.transitions.get(self.state):
            return True
        else:
            return False

    def check_conditions(self):
        if self.conditions:
            for condition in self.conditions:
                template = evaluate_template_input(self.to_dict(), condition)
                if not eval(template):
                    return False
        return True
