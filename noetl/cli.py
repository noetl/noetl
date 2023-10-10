import sys
import requests
import re
import os
from loguru import logger
import base64

cwd = os.getcwd()
csd = os.path.dirname(os.path.abspath(__file__))


class Goodbye:
    @staticmethod
    def exit():
        logger.info("\nGoodbye...")
        sys.exit()


def is_api_running():
    try:
        response = requests.get("http://localhost:8021/health")
        if response.status_code == 200:
            return True
    except Exception as e:
        logger.info(f"NoETL API is not healthy: {str(e)}.")
    return False


def command_api(tokens, metadata=None, payload=None):
    if payload is None:
        payload = {"message": "empty payload"}
    if metadata is None:
        metadata = {"message": "empty metadata"}
    logger.info(f"tokens: {tokens}, metadata: {metadata}, payload: {payload}")
    try:
        response = requests.post(
            "http://localhost:8021/command",
            json={"tokens": tokens, "metadata": metadata, "payload": payload}
        )
        response.raise_for_status()
        result = response.json()
        return result
    except requests.exceptions.Timeout:
        logger.error(f"NoETL API request timed out.")
        return None
    except requests.exceptions.ConnectionError:
        logger.error(f"NoETL API is not running.")
        return None
    except Exception as e:
        logger.error(f"NoETL command validation error: {str(e)}.")
        return None


def validate_command(command):
    if not is_api_running:
        logger.error("NoETL API not responding")
        raise
    pattern = re.compile(r'^add workflow config file (.+)$', re.IGNORECASE)
    match = pattern.match(command)
    if match:
        file_path = match.group(1).strip()
        if not os.path.exists(file_path):
            logger.error(f"File not found: {file_path}")
            return
        try:
            with open(file_path, 'r') as file:
                file_source = file.read()
                encoded_config = base64.b64encode(file_source.encode()).decode()
        except Exception as e:
            logger.error(f"Error reading file: {str(e)}")
            return

        metadata = {
            "source": "noetl-cli",
            "command": "api.add.workflow"
        }
        payload = {
            "config": encoded_config
        }

        response = command_api(tokens="add workflow config file", metadata=metadata, payload=payload)
        if response is not None:
            logger.info(response)
        else:
            logger.info("NoETL API is not responding.")
    else:
        metadata = {
            "source": "noetl-cli",
            "command": "api.spellcheck"
        }
        payload = {
            "command": command
        }
        result = command_api(tokens=command, metadata=metadata, payload=payload)
        if result is not None:
            logger.info(result)
        else:
            logger.info("NoETL API is not responding.")


def main():
    try:
        if len(sys.argv) > 1:
            command = " ".join(sys.argv[1:])
            logger.info(command)
            validate_command(command)
        else:
            logger.info("NoETL command line terminal.\nEnter a command or 'exit' to quit")
            while True:
                command = input("> ")
                if command.lower() == 'exit':
                    Goodbye.exit()
                    break
                validate_command(command.lstrip())
    except KeyboardInterrupt:
        Goodbye.exit()
    except Exception as e:
        logger.info(f"NoETL cli error: {str(e)}.")


if __name__ == "__main__":
    main()
