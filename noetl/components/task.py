from loguru import logger

from noetl.components import Kind
from noetl.components.fsm import FiniteAutomata
from noetl.components.action import Action
from noetl.components.meta import Metadata
from noetl.components.spec import Spec
from noetl.components.template import get_object_value


class Task(FiniteAutomata):
    """
    A Task class that represents a single task instance within a Job and inherits from the FiniteAutomata class.
    Args:
        workflow_name (str): The name of the parent Workflow.
        job_name (str): The name of the parent Job.
        job_spec (Spec): The specification of the parent Job.
        task_config (dict): A dictionary containing the parsed task configuration.
    """
    def __init__(self,
                 workflow_name: str,
                 job_name: str,
                 job_spec: Spec,
                 task_config: dict
                 ):
        """
        Initializes a new Task instance based on the provided configuration.
        Args:
            workflow_name (str): The name of the parent Workflow.
            job_name (str): The name of the parent Job.
            job_spec (Spec): The specification of the parent Job.
            task_config (dict): A dictionary containing the parsed task configuration.
        """
        metadata = Metadata(
            name=get_object_value(task_config, "name"),
            kind=Kind.TASK)
        spec = Spec()
        spec.state = job_spec.state
        spec.transitions = job_spec.transitions
        spec.conditions = get_object_value(task_config, "conditions")
        spec.instance_id = job_spec.instance_id
        spec.db = job_spec.db
        super().__init__(
            metadata=metadata,
            spec=spec
        )

        self.workflow_name: str = workflow_name
        self.job_name: str = job_name
        self.actions: list[Action] = []
        self.define_actions(actions_config=task_config.get("actions"))

    def define_actions(self, actions_config):
        """
        Defines the actions for the task based on the provided configuration.
        Args:
            actions_config (list): A list of dictionaries containing the parsed action configurations.
        """
        for id, action_config in enumerate(actions_config, start=1):
            action = Action(
                action=action_config,
                action_id=id
            )
            self.actions.append(action)

    async def execute(self):
        """
        Executes the Task instance by executing each action sequentially.
        Sets the Task state to "running" and logs the execution process.
        """
        self.set_state("running")
        logger.info(f"Executing task {self.metadata.name}")
        for action in self.actions:
            logger.info(action)
