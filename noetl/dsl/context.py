import copy
import datetime
import json
from copy import deepcopy
from typing import Dict, Any
from jinja2 import Template
from noetl.runtime.interp import resolve_system_paths
from noetl.runtime.scope import Scope
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

class Context(dict):
    def __init__(
            self,
            configs: Dict[str, Any],
            cwd_path: str = None,
            execution_start_time: datetime.datetime = None,
            execution_path: str = None,
            log_path: str = None,
            output_path: str = None,
            scope: Scope | None = None,
            storage_type: str = "json",
            break_on_failure: bool = None,
    ):

        super().__init__(configs)
        self.execution_start_time = execution_start_time or datetime.datetime.now()
        self.scope = scope or Scope().new_job_scope(job_name=self.get("jobName", "default_job"))
        self["jobId"] = self.scope.job_id
        self["executionStartTime"] = self.execution_start_time.isoformat()
        self.cwd_path = cwd_path or ""
        if not (execution_path and log_path and output_path):
            execution_path, log_path, output_path = resolve_system_paths(
                config=self, #.get("system", {}),
                context=self,
                cwd_path=self.cwd_path,
            )
        self.execution_path = execution_path
        self.log_path = log_path
        self.output_path = output_path
        self["executionPath"] = self.execution_path
        self["logPath"] = self.log_path
        self["outputPath"] = self.output_path
        self.break_on_failure = break_on_failure if break_on_failure is not None else self.get("break", True)
        self.storage_type = storage_type or self.get("storageType", "json")
        self._state = {}
        self.templates = self.get("templates", {})

    def __repr__(self):

        def custom_serializer(obj):
            if isinstance(obj, datetime.datetime):
                return obj.isoformat()
            raise TypeError(f"Type {type(obj)} is not JSON serializable")

        return json.dumps(self, indent=2, default=custom_serializer)

    def break_on_failure(self):
        return self.break_on_failure

    def get_job_id(self):
        return self.scope.job_id

    def get_execution_path(self):
        return self.execution_path

    def get_log_path(self):
        return self.log_path

    def get_output_path(self):
        return self.output_path

    def get_state(self, key: str, default: Any = None) -> Any:
        return self._state.get(key, default)

    def update_state(self, key: str, value: Any) -> None:
        self._state[key] = value

    def get_steps(self):
        return self.get("steps", [])

    def get_tasks(self):
        tasks = self.get("tasks", [])
        if isinstance(tasks, dict):
            tasks = [{"task": key, **value} for key, value in tasks.items()]
        return tasks

    def new_step_context(self, step_config: dict) -> "Context":
        step_name = step_config.get("step")
        if not step_name:
            raise ValueError(f"Missing step key in step configuration: {step_config}")

        if not isinstance(step_config, dict):
            raise ValueError(f"Invalid step configuration (not a dict): {step_config}")
        global_tasks = self.get("tasks", [])
        step_tasks = [
            task for task in global_tasks
            if task.get("task") in step_config.get("tasks", [])
        ]
        step_config["tasks"] = step_tasks
        new_step_scope = self.scope.new_step_scope(step_name)
        configs = deepcopy({**self, "stepConfig": step_config, "stepName": step_name, **step_config})
        return Context(
            configs=configs,
            cwd_path=self.cwd_path,
            scope=new_step_scope,
            execution_start_time=self.execution_start_time,
            execution_path=self.execution_path,
            log_path=self.log_path,
            output_path=self.output_path,
            storage_type=self.storage_type,
            break_on_failure=self.break_on_failure,
        )

    def new_task_context(self, task_name: str) -> "Context":
        global_tasks = self.get_tasks()
        task_config = next(
            (task for task in global_tasks if task.get("task") == task_name),
            None
        )
        if not task_config:
            raise ValueError(f"Task configuration for '{task_name}' not found in tasks.")
        task_config["loop"] = task_config.get("loop", {})
        new_task_scope = self.scope.new_task_scope(task_name)
        configs = deepcopy({**self, "taskName": task_name, **task_config})
        return Context(
            configs=configs,
            cwd_path=self.cwd_path,
            scope=new_task_scope,
            execution_start_time=self.execution_start_time,
            execution_path=self.execution_path,
            log_path=self.log_path,
            output_path=self.output_path,
            storage_type=self.storage_type,
            break_on_failure=self.break_on_failure,
        )

    def new_action_context(self, action_config: dict, action_id: str) -> "Context":
        if not isinstance(action_config, dict):
            raise ValueError(
                f"Expected action_config type of dict but got {type(action_config)}: {action_config}"
            )
        loop_config = action_config.get("loop", {})
        action_config["loop"] = loop_config
        new_action_scope = self.scope.new_action_scope(action_id)
        configs = deepcopy({**self, "actionConfig": action_config, "loop": loop_config})
        return Context(
            configs=configs,
            cwd_path=self.cwd_path,
            scope=new_action_scope,
            execution_start_time=self.execution_start_time,
            execution_path=self.execution_path,
            log_path=self.log_path,
            output_path=self.output_path,
            storage_type=self.storage_type,
            break_on_failure=self.break_on_failure,
        )

    def new_item_context(self, item_config: dict, item: str) -> "Context":
        if not item:
            raise ValueError("Loop item cannot be empty.")
        new_item_config = item_config.get("loop", {})
        new_item_scope = self.scope.new_item_scope(item)
        return Context(
            configs=deepcopy(self | item_config),
            cwd_path=self.cwd_path,
            scope=new_item_scope,
            execution_start_time=self.execution_start_time,
            execution_path=self.execution_path,
            log_path=self.log_path,
            output_path=self.output_path,
            storage_type=self.storage_type,
            break_on_failure=self.break_on_failure,
        )


    def clone_context(self, updates: Dict[str, Any]) -> "Context":
        new_configs = copy.deepcopy(self)
        new_configs.update(updates)
        return Context(configs=new_configs, cwd_path=self.cwd_path)


    def render_context(self, template: str) -> str:
        context = copy.deepcopy(self)
        try:
            rendered = Template(template).render(context)
            return rendered
        except Exception as e:
            logger.error(f"Error rendering template: {e}")
            raise

    def render_template(self, template: str) -> str:
        try:
            return Template(template).render(self)
        except Exception as e:
            logger.error(f"Error rendering template '{template}': {e}")
            raise
