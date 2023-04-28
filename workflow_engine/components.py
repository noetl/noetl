import asyncio
import subprocess
import aiohttp
from typing import Optional
from loguru import logger
from croniter import croniter
from datetime import datetime
from enum import Enum
import re


class Automata(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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

    @staticmethod
    def get_all_matches(input_string: str):
        pattern = r"{{\s*(.*?)\s*}}"
        matches = re.findall(pattern, input_string)
        return matches

    def get_match(self, match):
        key = match.group(1)
        return self.get_value(key)

    def evaluate_input(self, input_string):
        return re.sub(r"{{\s*(.*?)\s*}}", self.get_match, input_string)


automata = Automata()


class State(Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StateMachine:
    def __init__(self, initial_state: State = State.IDLE):
        self.state: State = initial_state

    def set_state(self, new_state: State):
        if self.can_transition(new_state):
            self.state = new_state
        else:
            raise ValueError(f"Invalid state transition from {self.state} to {new_state}")

    def can_transition(self, new_state: State):
        if self.state == State.IDLE and new_state == State.RUNNING:
            return True
        elif self.state == State.RUNNING and new_state in [State.COMPLETED, State.FAILED]:
            return True
        else:
            return False


class BaseAction:
    def __init__(self, name: str, conditions: None):
        self.name = name
        self.state_machine = StateMachine()
        self.conditions: Optional[list] = conditions or []

    def __str__(self):
        return f"{self.__class__.__name__}(name={self.name})"

    def __repr__(self):
        return '{%s}' % str(', '.join('%s : %s' % (k, repr(v)) for (k, v) in self.__dict__.items()))

    def info(self):
        print(f"{self.__class__.__name__} name: {self.name}")

    def check_conditions(self):

        for condition in self.conditions:
            template = automata.evaluate_input(condition)
            logger.info(f"{self.name} condition {template}")
            if not eval(template):
                return False
        return True


class Workflow(BaseAction):
    def __init__(self, name: str, conditions: Optional[list] = None, jobs: Optional[list] = None, schedule: Optional[str] = None,
                 variables: Optional[dict] = None):
        super().__init__(name, conditions)
        self.jobs: Optional[list] = jobs or []
        self.schedule: Optional[str] = schedule
        self.variables: Optional[dict] = variables or {}

    async def execute(self):
        self.state_machine.set_state(State.RUNNING)
        logger.info(f"Executing workflow {self.name}")
        for job in self.jobs:
            await job.execute()


class Job(BaseAction):
    def __init__(self, name: str, workflow_name: str, tasks=None, runtime=None, schedule=None, conditions: Optional[list] = None,
                 **kwargs):
        super().__init__(name, conditions)
        self.workflow_name: str = workflow_name
        self.tasks = tasks or []
        self.runtime = runtime
        self.schedule = schedule
        self.extra_params = kwargs

    def get_status(self):
        return automata.get_value(f"{self.workflow_name}.jobs.{self.name}.status")

    def set_status(self, status):
        automata.set_value(f"{self.workflow_name}.jobs.{self.name}.status", status)

    async def execute(self):
        self.state_machine.set_state(State.RUNNING)
        logger.info(f"Executing job {self.name}")
        for task in self.tasks:
            await task.execute()

    def job_ready(self) -> bool:
        if self.get_status != "pending":
            return False

        if self.schedule:
            now = datetime.now()
            iter = croniter(self.schedule, now)
            next_scheduled_time = iter.get_next(datetime)
            logger.info(f"Next scheduled time {next_scheduled_time}")
            if next_scheduled_time > now:
                return False




class Task(BaseAction):
    def __init__(self, name: str, workflow_name: str, job_name: str, variables: str = None, kind: str = 'shell',
                 command: str = None, method: str = None,
                 url: str = None, timeout: str = None, loop: dict = None, conditions: Optional[list] = None, **kwargs):
        super().__init__(name, conditions)
        self.workflow_name: str = workflow_name
        self.job_name: str = job_name
        self.variables: Optional[dict] = variables
        self.kind: str = kind
        self.command: Optional[str] = command
        self.method: Optional[str] = method
        self.url: Optional[str] = url
        self.timeout: Optional[str] = timeout
        self.loop: Optional[dict] = loop
        self.status = None
        self.output = None
        self.extra_params = kwargs

    async def execute(self):
        self.state_machine.set_state(State.RUNNING)
        logger.info(f"Executing task {self.name}")
        if self.conditions and not self.check_conditions():
            logger.info(f"Skipping task {self.name} due to unmet conditions")
            return
        if self.kind == 'shell':
            await self.execute_shell()
        elif self.kind == 'rest_api':
            await self.execute_rest_api()
        else:
            logger.info(f"Unknown kind for task {self.name}")

    # def check_conditions(self):
    #
    #     for condition in self.conditions:
    #         template = automata.evaluate_input(condition)
    #         logger.info(f"{self.name} condition {template}")
    #         if not eval(template):
    #             return False
    #     return True

    async def execute_shell(self):
        process = await asyncio.create_subprocess_shell(self.command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = await process.communicate()
        self.output = stdout.decode().strip()
        automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.output", self.output)
        self.status = 'success' if process.returncode == 0 else 'failure'
        automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.status", self.status)
        logger.info(f"Task {self.name} completed with status: {self.status} output: {self.output}")

    async def execute_rest_api(self):
        async with aiohttp.ClientSession() as session:
            async with session.request(self.method, self.url) as response:
                self.output = await response.text()
                automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.output", self.output)
                self.status = 'success' if response.status == 200 else 'failure'
                automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.status", self.status)
                logger.info(f"Task {self.name} completed with status {self.status}")
