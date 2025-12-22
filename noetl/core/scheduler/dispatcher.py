from __future__ import annotations
from typing import List
from .plan_types import Schedule, StepSpec


class Dispatcher:
    """Stub dispatcher that would enqueue jobs to workers respecting earliest starts.

    For minimal scope in this change, we only keep the interface. Server integration is out of scope.
    """

    def __init__(self):
        pass

    def dispatch(self, schedule: Schedule, steps: List[StepSpec]):
        # Placeholder: in a real system, we would enqueue based on schedule.starts_ms and resource tags
        return {
            "enqueued": [s.id for s in steps],
            "plan": {
                "starts_ms": schedule.starts_ms,
                "ends_ms": schedule.ends_ms,
            },
        }
