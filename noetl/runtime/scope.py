import datetime
import random
import string
from dataclasses import dataclass, replace
from typing import Optional, Tuple

def generate_job_id() -> str:
    start_date_time = datetime.datetime.now()
    timestamp = start_date_time.strftime("%Y%m%d_%H%M%S")
    milliseconds = f"{start_date_time.microsecond:06d}"
    random_suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"{timestamp}_{milliseconds}_{random_suffix}"


@dataclass
class Scope:
    job_name: Optional[str] = None
    job_id: Optional[str] = None

    step_name: Optional[str] = None
    step_item: Optional[str] = None

    task_name: Optional[str] = None
    task_item: Optional[str] = None

    action_id: Optional[str] = None
    action_item: Optional[str] = None

    level: str = "job"  # "job", "step", "task", "action"

    def log_id(self) -> str:
        components = []
        if self.job_id:
            components.append(f"job:{self.job_id}")
        if self.step_name:
            components.append(f"step:{self.step_name}")
        if self.step_item:
            components.append(f"stepItem:{self.step_item}")
        if self.task_name:
            components.append(f"task:{self.task_name}")
        if self.task_item:
            components.append(f"taskItem:{self.task_item}")
        if self.action_id:
            components.append(f"action:{self.action_id}")
        if self.action_item:
            components.append(f"actionItem:{self.action_item}")
        return " -> ".join(components)

    def get_id(self):
        return {"scope": self.log_id()}

    def new_job_scope(self, job_name: str = "default_job") -> "Scope":
        job_id = generate_job_id()
        return replace(self, job_name=job_name, job_id=job_id, level="job")

    def new_step_scope(self, step_name: str) -> "Scope":
        return replace(
            self,
            step_name=step_name,
            step_item=None,
            task_name=None,
            task_item=None,
            action_id=None,
            action_item=None,
            level="step",
        )

    def new_task_scope(self, task_name: str) -> "Scope":
        return replace(
            self,
            task_name=task_name,
            task_item=None,
            action_id=None,
            action_item=None,
            level="task",
        )

    def new_action_scope(self, action_id: str) -> "Scope":
        return replace(
            self,
            action_id=action_id,
            action_item=None,
            level="action",
        )

    def new_item_scope(self, item: str) -> "Scope":
        if self.level == "step":
            return replace(self, step_item=item)
        elif self.level == "task":
            return replace(self, task_item=item)
        elif self.level == "action":
            return replace(self, action_item=item)
        else:
            raise ValueError(f"Loop items are not supported for the current level: {self.level}")
