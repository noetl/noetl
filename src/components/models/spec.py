from typing import Optional, Any
from loguru import logger
from src.components import BaseRepr


class Spec(BaseRepr):
    """
    Spec class to store specifications.
    """

    def __init__(self, initial_state: Optional[str] = None, transitions: Optional[dict[str, list[str]]] = None):
        self.variables: Optional[dict] = None
        self.arguments: Optional[dict] = None
        self.environments: Optional[dict] = None
        self.initial_state: Optional[str] = initial_state
        self.transitions: Optional[dict[str, list[str]]] = transitions
        self.conditions: Optional[list[str]] = None

    def set_vars(self, variables: dict = None):
        if variables is None:
            logger.error("Expected dict of variables, but got nothing")
        else:
            self.variables = self.variables | variables

    def set_args(self, arguments: dict = None):
        if arguments is None:
            logger.error("Expected dict of arguments, but got nothing")
        else:
            self.arguments = self.arguments | arguments

    def set_envs(self, environments: dict = None):
        if environments is None:
            logger.error("Expected dict of environment variables, but got nothing")
        else:
            self.environments = self.environments | environments


class DispatcherSpecWorkflow:
    def __init__(self, config_path: str):
        self.config_path: str = config_path


class DispatcherSpec(Spec):
    def __init__(self,
                 instance_id: Optional[str] = None
                 ):
        super().__init__()
        self.instance_id: Optional[str] = instance_id
        self.workflows: list[DispatcherSpecWorkflow] = list()


class WorkflowSpec(Spec):

    def __init__(self,
                 instance_id: Optional[str] = None,
                 schedule: Optional[str] = None,
                 workflows: Optional[Any] = None):
        super().__init__()
        self.instance_id: Optional[str] = instance_id
        self.schedule: Optional[str] = schedule
        self.jobs: Optional[Any] = workflows


class JobSpec(Spec):

    def __init__(self,
                 schedule: Optional[str] = None,
                 tasks: Optional[Any] = None):
        super().__init__()
        self.schedule: Optional[str] = schedule
        self.tasks: Optional[Any] = tasks


class TaskSpec(Spec):

    def __init__(self,
                 actions: Optional[Any] = None):
        super().__init__()
        self.actions: Optional[Any] = actions


class ActionSpec(Spec):

    def __init__(self,
                 shell: Optional[str] = None,
                 http_request: Optional[dict] = None
                 ):
        super().__init__()
        self.shell: Optional[str] = shell
        self.http_request: Optional[dict] = http_request
