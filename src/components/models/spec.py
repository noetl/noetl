from typing import Optional
from loguru import logger
from src.components import BaseRepr
from src.components.models.template import DictTemplate


class WorkflowConfigPath(BaseRepr):
    def __init__(self, config_path: str):
        self.path = config_path


class Spec(BaseRepr):
    """
    Spec class to store specifications.
    """

    def __init__(self, spec: DictTemplate):
        self.workflow_config_paths: Optional[list[WorkflowConfigPath]] = None  # Dispatcher
        # all other specs
        self.vars: Optional[dict] = None
        self.args: Optional[dict] = None
        self.envs: Optional[dict] = None
        self.initial_state: Optional[str] = spec.get_value("initialState")
        self.schedule: Optional[str] = spec.get_value("schedule")
        self.transitions: Optional[dict[str, list[str]]] = spec.get_value("transitions")
        self.conditions: Optional[list[str]] = spec.get_value("conditions")

        self.set_vars(spec.get_value("vars"))
        self.set_args(spec.get_value("args"))
        self.set_envs(spec.get_value("envs"))
        self.set_workflow_config_paths(spec.get_value("workflowConfigPaths"))
        logger.info(f"Specification initialized {spec}")

    def set_vars(self, vars: dict = None):
        if vars is not None:
            if self.vars is None:
                self.vars = vars
            else:
                self.vars |= vars

    def set_args(self, args: dict = None):
        if args is not None:
            if self.args is None:
                self.args = args
            else:
                self.args |= args

    def set_envs(self, envs: dict = None):
        if envs is not None:
            if self.envs is None:
                self.envs = envs
            else:
                self.envs |= envs

    def set_workflow_config_paths(self, workflow_config_paths: dict = None):
        if workflow_config_paths is not None:
            for item in workflow_config_paths:
                path = item.get("configPath")
                if path:
                    if self.workflow_config_paths is None:
                        self.workflow_config_paths = list()
                    self.workflow_config_paths.append(WorkflowConfigPath(path))
