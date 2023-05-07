from enum import Enum
from typing import Optional, Union
from loguru import logger
from workflow_engine.src.components.config import Config
from workflow_engine.src.storage.redis_storage import RedisStorage
import re


class State(Enum):
    """
    The State Enum class represents the various states that an entity
    in the workflow engine, such as a workflow, job, or task, can have
    during its execution.
    Attributes:
        READY (str): The entity is ready to be executed.
        RUNNING (str): The entity is currently running.
        IDLE (str): The entity is waiting for a condition or dependency to be fulfilled.
        COMPLETED (str): The entity has successfully completed its execution.
        FAILED (str): The entity has failed to complete its execution.
    """
    READY = "ready"
    RUNNING = "running"
    IDLE = "idle"
    COMPLETED = "completed"
    FAILED = "failed"


class FiniteAutomata:
    """
    The FiniteAutomata class is the base class for all entities in the workflow engine,
    such as workflows, jobs, and tasks. It provides common functionality like state management,
    condition checking, and storage connection.
    Attributes:
        state (State): The current state of the entity.
        name (str): The name of the entity.
        config (Config): The configuration object.
        db (Union[RedisStorage, None]): The storage object for the entity.
        instance_id (str): The unique instance ID of the entity.
        conditions (list): The list of conditions that must be fulfilled for the entity to be executed.
        workflow_template (dict): The workflow template as a dictionary.
    """

    def __init__(self,
                 initial_state: State = State.READY,
                 instance_id: Optional[str] = None,
                 name: Optional[str] = None,
                 config: Optional[Config] = None,
                 conditions: Optional[list] = None

                 ):
        """
        Initializes a FiniteAutomata object with the given parameters.
        Args:
            instance_id (str): The unique instance ID of the workflow object.
            initial_state (State, optional): The initial state of the entity. Defaults to State.READY.
            name (Optional[str], optional): The name of the entity. Defaults to None.
            config (Optional[Config], optional): The configuration object. Defaults to None.
            conditions (Optional[list], optional): The list of conditions that must be fulfilled for the entity to be executed. Defaults to None.
        """
        self.state: State = initial_state
        self.name: str = name
        self.config: Optional[Config] = config
        self.db: Optional[Union[RedisStorage]] = None
        self.instance_id = instance_id
        self.conditions: Optional[list] = conditions or []
        self.workflow_template: dict = {}

    def __repr__(self):
        return '{%s}' % str(', '.join('%s : %s' % (k, repr(v)) for (k, v) in self.__dict__.items()))

    def print(self):
        """
        Prints the string representation of the FiniteAutomata object.
        """
        logger.info(self.__repr__())

    def __str__(self):
        return f"{self.__class__.__name__}(name={self.name})"

    def set_state(self, new_state: State):
        """
        Sets the state of the entity to the given new_state if the transition is allowed.
        Args:
            new_state (State): The new state to be set.
        Raises:
            ValueError: If the state transition is not allowed.
        """
        if self.can_transition(new_state):
            self.state = new_state
        else:
            raise ValueError(f"Invalid state transition from {self.state} to {new_state}")

    def can_transition(self, new_state: State):
        """
        Checks if the entity can transition from its current state to the given new_state.
        Args:
            new_state (State): The new state to be checked.
        Returns:
            bool: True if the transition is allowed, False otherwise.
        """
        if self.state == State.READY and new_state == State.RUNNING:
            return True
        elif self.state == State.RUNNING and new_state in [State.COMPLETED, State.FAILED]:
            return True
        else:
            return False

    async def set_config(self):
        if self.config:
            self.config = Config()

    async def set_storage(self):
        """
        Sets up the storage for the FiniteAutomata object, based on the given configuration, Redis by default.
        """
        logger.info(self.config.redis_config)
        try:
            # TODO add select option for base storage abstraction
            if self.db is None:
                self.db = RedisStorage(config=self.config.redis_config)
        except Exception as e:
            logger.error(f"Setting up a storage failed {e}")

    async def connect_storage(self):
        """
        Connects to the storage pool.
        """
        if self.db:
            # TODO add a select pool logic based on based storage abstraction
            await self.db.pool_connect()

    def check_conditions(self):
        """
        Checks if all conditions in the conditions list are fulfilled.
        Returns:
            bool: True if all conditions are fulfilled, False otherwise.
        """
        for condition in self.conditions:
            template = self.evaluate_input(condition)
            logger.info(f"{self.name} condition {template}")
            if not eval(template):
                return False
        return True

    def get_value(self, path_str):
        keys = path_str.split(".")
        value = self
        for key in keys:
            value = value.get(key)
            if value is None:
                return None
        return value

    def set_value(self, path, value):
        keys = path.split('.')
        current_path = self
        for key in keys[:-1]:
            if key not in current_path:
                current_path[key] = {}
            current_path = current_path[key]
        current_path[keys[-1]] = value

    def get_match(self, match):
        key = match.group(1)
        return self.get_value(key)

    def evaluate_input(self, input_string):
        return re.sub(r"{{\s*(.*?)\s*}}", self.get_match, input_string)
