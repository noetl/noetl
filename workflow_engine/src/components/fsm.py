from enum import Enum
from typing import Optional, Union, Any
from loguru import logger
from workflow_engine.src.components.config import Config
from workflow_engine.src.components.template import evaluate_template_input
from workflow_engine.src.storage.redis_storage import RedisStorage



class Kind(Enum):
    """
    Enum class to represent the different kinds of entities.
    """
    WORKFLOW = "workflow"
    JOB = "job"
    TASK = "task"
    ACTION = "action"


class Metadata:
    """
    Metadata class to store information.
    """
    def __init__(self, name: str, kind: Kind):
        """
        Initializes a Metadata instance with the given name and kind.

        Args:
            name (str): The name of the entity.
            kind (Kind): The kind of the entity.
        """
        self.name: str = name
        self.kind: Kind = kind
        self.desc: Optional[str] = None


class Spec:
    """
    Spec class to store specifications.
    """
    def __init__(self):
        """
        Initializes an empty Spec instance.
        """
        self.instance_id: Optional[str] = None,
        self.schedule: Optional[str] = None
        self.runtime: Optional[Any] = None
        self.variables: Optional[dict] = None
        self.state: Optional[str] = None
        self.transitions: Optional[dict[str, list[str]]] = None
        self.conditions: Optional[list] = None
        self.db: Optional[Union[RedisStorage]] = None


class FiniteAutomata:
    """
    The FiniteAutomata class is the base class for all entities in the workflow engine,
    such as workflows, jobs, tasks, and actions. It provides common functionality like state management,
    condition checking, and storage connection.

    Attributes:
        metadata (Metadata): The metadata of the entity.
        spec (Spec): The specification of the entity.
        config (Optional[Config]): The configuration object.
    """

    def __init__(self,
                 metadata: Metadata,
                 spec: Spec = Spec(),
                 config: Optional[Config] = None,
                 ):
        """
        Initializes a FiniteAutomata object with the given parameters.

        Args:
            metadata (Metadata): The metadata.
            spec (Spec, optional): The specification.
            config (Optional[Config], optional): The configuration object.
        """
        self.metadata: Metadata = metadata
        self.spec: Spec = spec
        self.config: Optional[Config] = config
    def __repr__(self):
        return '{%s}' % str(', '.join('%s : %s' % (k, repr(v)) for (k, v) in self.__dict__.items()))

    def print(self):
        """
        Prints the string representation of the FiniteAutomata object.
        """
        logger.info(self.__repr__())

    def __str__(self):
        return f"{self.__class__.__name__}(name={self.metadata.name})"

    def set_state(self, new_state: str):
        """
        Sets the state of the entity to the given new_state if the transition is allowed.

        Args:
            new_state (str): The new state to be set.

        Raises:
            ValueError: If the state transition is not allowed.
        """
        if self.can_transition(new_state):
            self.state = new_state
        else:
            raise ValueError(f"Invalid state transition from {self.state} to {new_state}")

    def can_transition(self, new_state: str):
        """
        Checks if the entity can transition from its current state to the given new_state.

        Args:
            new_state (str): The new state to be checked.

        Returns:
            bool: True if the transition is allowed, False otherwise.
        """
        if new_state in self.spec.transitions.get(self.spec.state):
            return True
        else:
            return False

    async def set_config(self):
        """
        Sets the configuration for the FiniteAutomata object, if a configuration object is provided.
        """
        if self.config:
            self.config = Config()

    async def set_storage(self):
        """
        Sets up the storage for the FiniteAutomata object, based on the given configuration, Redis by default.
        """
        logger.info(self.config.redis_config)
        try:
            # TODO add select option for base storage abstraction
            if self.spec.db is None:
                self.spec.db = RedisStorage(config=self.config.redis_config)
        except Exception as e:
            logger.error(f"Setting up a storage failed {e}")

    async def connect_storage(self):
        """
        Connects to the storage pool.
        """
        if self.spec.db:
            # TODO add a select pool logic based on based storage abstraction
            await self.spec.db.pool_connect()

    def check_conditions(self):
        """
        Checks if all conditions in the conditions list are fulfilled.

        Returns:
            bool: True if all conditions are fulfilled, False otherwise.
        """
        for condition in self.spec.conditions:
            template = evaluate_template_input(self, condition)
            logger.info(f"{self.metadata.name} condition {template}")
            if not eval(template):
                return False
        return True

    # def get_value(self, path_str):
    #     keys = path_str.split(".")
    #     value = self
    #     for key in keys:
    #         value = value.get(key)
    #         if value is None:
    #             return None
    #     return value
    #
    # def set_value(self, path, value):
    #     keys = path.split('.')
    #     current_path = self
    #     for key in keys[:-1]:
    #         if key not in current_path:
    #             current_path[key] = {}
    #         current_path = current_path[key]
    #     current_path[keys[-1]] = value
    #
    # def get_match(self, match):
    #     key = match.group(1)
    #     return self.get_value(key)
    #
    # def evaluate_input(self, input_string):
    #     return re.sub(r"{{\s*(.*?)\s*}}", self.get_match, input_string)
