import sys
import requests
import psutil
import os
from enum import Enum
from loguru import logger

cwd = os.getcwd()
csd = os.path.dirname(os.path.abspath(__file__))


class Goodbye:
    @staticmethod
    def exit():
        logger.info("\nGoodbye...")
        sys.exit()


class SystemService(Enum):
    COMMAND_API = "command-api"
    EVENT_API = "event-api"
    DISPATCHER = "dispatcher"

    @classmethod
    def create(cls, value):
        for member in cls:
            if member.value == value:
                return member
        raise ValueError(f"No Service with value {value} in {cls.__name__}")

    def get_module(self):
        if self == SystemService.COMMAND_API:
            return "command"
        elif self == SystemService.EVENT_API:
            return "event"
        elif self == SystemService.DISPATCHER:
            return "dispatcher"
        else:
            return None

    def get_module_path(self):
        module_path = os.path.join(csd, f"{self.get_module()}")
        if os.path.isfile(f"{module_path}.py"):
            logger.info(f"Path to {self.get_module()}: {module_path}")
        else:
            logger.error(f"{self.get_module()} not found in the {csd}.")
        return module_path


def is_process_running(service_name):
    if service_name.value == SystemService.COMMAND_API.value:
        return is_command_api_running()
    for process in psutil.process_iter(attrs=['name']):
        if process.info['name'] == service_name.value:
            return True
    return False


def is_command_api_running():
    try:
        response = requests.get("http://localhost:8021/health")
        if response.status_code == 200:
            return True
    except Exception as e:
        logger.info(f"Error Command API is not healthy: {str(e)}.")
    return False


def command_api(command_text):
    try:
        response = requests.post("http://localhost:8021/process-command", json={"command_text": command_text})
        response.raise_for_status()
        result = response.json()
        return result
    except requests.exceptions.Timeout:
        logger.info(f"Command API request timed out.")
        return None
    except requests.exceptions.ConnectionError:
        logger.info(f"Command API is not running.")
        return None
    except Exception as e:
        logger.info(f"Error validating command with Command API: {str(e)}.")
        return None


def system_command(command_text):
    tokens = command_text.strip().lower().split()
    if "service" in tokens:
        action_index = None
        for action in ["status"]:
            if action in tokens:
                action_index = tokens.index(action)
                break
        if action_index is not None:
            action = tokens[action_index]
            service_tokens = tokens[action_index + 1:]
            arguments = " ".join(service_tokens[1:])
            service_action(action, SystemService.create(service_tokens[0]), arguments)
        else:
            logger.info("Invalid service action.")
    else:
        logger.info("Invalid system command.")


def service_action(action, service_name, arguments):
    if action == "status":
        if is_process_running(service_name):
            logger.info(f"{service_name} is running.")
        else:
            logger.info(f"{service_name} is not running.")


def validate_command_path(command):
    if command.startswith("service"):
        system_command(command)
    else:
        result = command_api(command)
        if result is not None:
            logger.info(result)
        else:
            logger.info("No response from the Command API.")


def main():
    try:
        if len(sys.argv) > 1:
            command = " ".join(sys.argv[1:])
            logger.info(command)
            validate_command_path(command)
        else:
            logger.info("NoETL command line terminal.\nEnter a command or 'exit' to quit")
            while True:
                command = input("> ")
                if command.lower() == 'exit':
                    Goodbye.exit()
                    break
                validate_command_path(command.lstrip())
    except KeyboardInterrupt:
        Goodbye.exit()
    except Exception as e:
        logger.info(f"NoETL cli Error: {str(e)}.")


if __name__ == "__main__":
    main()
