from typing import Optional
from loguru import logger
from workflow_engine.src.components.finite_automata import FiniteAutomata
from workflow_engine.src.components.action import Action


class Task(FiniteAutomata):
    """
    A Task class that represents a single task instance within a Job and inherits from the FiniteAutomata class.
    Args:
        workflow_name (str): The name of the parent Workflow.
        job_name (str): The name of the parent Job.
        instance_id (str): The unique instance ID of the parent Workflow.
        task_config (dict): A dictionary containing the parsed task configuration.
    """

    def __init__(self,
                 workflow_name: str,
                 job_name: str,
                 instance_id: str,
                 task_config: dict,
                 actions: Optional[list[Action]] = None
                 ):
        """
        Initializes a new Task instance based on the provided configuration.
        Args:
            workflow_name (str): The name of the parent Workflow.
            job_name (str): The name of the parent Job.
            instance_id (str): The unique instance ID of the parent Workflow.
            task_config (dict): A dictionary containing the parsed task configuration.
        """
        super().__init__(name=task_config.get("name"), instance_id=instance_id,
                         conditions=task_config.get("conditions"))
        self.workflow_name: str = workflow_name
        self.job_name: str = job_name
        if actions is None:
            actions = []
            for id, action in enumerate(task_config.get("actions"), start=1):
                actions.append(Action(action, id))

        self.actions: list[Action] = actions
        self.output = None

    async def execute(self):
        """
         Executes the Task instance based on its kind. The supported kinds are 'shell' and 'rest_api'.
         Sets the Task state to RUNNING and logs the execution process.
         """
        self.set_state("running")
        logger.info(f"Executing task {self.name}")
        for action in self.actions:
            logger.info(action)
        # if self.conditions and not self.check_conditions():
        #     logger.info(f"Skipping task {self.name} due to unmet conditions")
        #     return
        # if self.kind == 'shell':
        #     await self.execute_shell()
        # elif self.kind == 'rest_api':
        #     await self.execute_rest_api()
        # else:
        #     logger.info(f"Unknown kind for task {self.name}")

    # def check_conditions(self):
    #
    #     for condition in self.conditions:
    #         template = automata.evaluate_input(condition)
    #         logger.info(f"{self.name} condition {template}")
    #         if not eval(template):
    #             return False
    #     return True
