from loguru import logger
import asyncio
import subprocess
import aiohttp

class Action:
    """
    An Action class that represents a specific action to be executed within a Task.
    Args:
        action (dict): A dictionary containing the parsed action configuration.
        id (int): The ID of the action.
    """
    def __init__(self, action , id = 1):
        """
        Initializes a new Action instance based on the provided configuration.
        Args:
            action (dict): A dictionary containing the parsed action configuration.
            id (int): The ID of the action.
        """
        self.spec = {}
        self.kind = None
        self.name = None
        self.evaluate(action, id)

    def evaluate(self, action, id):
        """
        Evaluates the action configuration and sets the corresponding attributes of the Action instance.
        Args:
            action (dict): A dictionary containing the parsed action configuration.
            id (int): The ID of the action.
        """
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
        """
        Executes the action based on its kind.
        """
        if self.kind == 'shell':
            await self.execute_shell()
        elif self.kind == 'rest_api':
            await self.execute_rest_api()
        else:
            logger.info(f"Unknown kind: {self.kind}")

    async def execute_shell(self):
        """
        Executes the shell command action.
        """
        process = await asyncio.create_subprocess_shell(self.spec.get('command'), stdout=subprocess.PIPE,
                                                        stderr=subprocess.PIPE)
        stdout, stderr = await process.communicate()
        self.output = stdout.decode().strip()

        self.status = 'success' if process.returncode == 0 else 'failure'

        logger.info(f"Task {self.name} completed with status: {self.status} output: {self.output}")

    async def execute_rest_api(self):
        """
        Executes the REST API action.
        """
        async with aiohttp.ClientSession() as session:
            async with session.request(self.spec.get("method"), self.spec.get("url")) as response:
                self.output = await response.text()
                self.status = 'success' if response.status == 200 else 'failure'
                logger.info(f"Task {self.name} completed with status {self.status}")
