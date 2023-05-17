from loguru import logger
import asyncio
import subprocess
import aiohttp


class Action:
    def __init__(self, action , id = 1):
        self.spec = {}
        self.kind = None
        self.name = None
        self.evaluate(action, id)

    def evaluate(self, action, id):
        if action is None:
            logger.error(f"Can't evaluate {self.__dict__}")
        else:
            for k, v in action.items():
                self.kind = k
                self.name = f"{k}_{id}"
                if k == "shell":
                    self.spec["command"] = v
                if k == "rest_api":
                    self.spec['method'] = v.get('method')
                    self.spec['url'] = v.get('url')
                    self.spec['query'] = v.get('query')
        logger.info(self.__dict__)
    async def execute(self):
        # if self.conditions and not self.check_conditions():
        #     logger.info(f"Skipping task {self.name} due to unmet conditions")
        #     return
        if self.kind == 'shell':
            await self.execute_shell()
        elif self.kind == 'rest_api':
            await self.execute_rest_api()
        else:
            logger.info(f"Unknown kind: {self.kind}")

    async def execute_shell(self):
        """
        Executes the Task instance as a shell command.
        Logs the task completion status and output.
        """
        process = await asyncio.create_subprocess_shell(self.spec.get('command'), stdout=subprocess.PIPE,
                                                        stderr=subprocess.PIPE)
        stdout, stderr = await process.communicate()
        self.output = stdout.decode().strip()
        # automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.output", self.output)
        self.status = 'success' if process.returncode == 0 else 'failure'
        # automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.status", self.status)
        logger.info(f"Task {self.name} completed with status: {self.status} output: {self.output}")

    async def execute_rest_api(self):
        """
        Executes the Task instance as a REST API request.
        Logs the task completion status.
        """
        async with aiohttp.ClientSession() as session:
            async with session.request(self.spec.get("method"), self.spec.get("url")) as response:
                self.output = await response.text()
                # automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.output", self.output)
                self.status = 'success' if response.status == 200 else 'failure'
                # automata.set_value(f"{self.workflow_name}.jobs.{self.job_name}.tasks.{self.name}.status", self.status)
                logger.info(f"Task {self.name} completed with status {self.status}")
