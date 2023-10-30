import sys
import requests
import re
import os
import json
from loguru import logger
import base64

cwd = os.getcwd()
csd = os.path.dirname(os.path.abspath(__file__))


class Goodbye:
    @staticmethod
    def exit():
        logger.info("\nGoodbye...")
        sys.exit()


class GraphqlMutation:
    @staticmethod
    def register_workflow_config(payload, tokens=None, metadata=None):
        mutation = """
        mutation RegisterWorkflowConfig($payload: JSON!, $metadata: JSON,$tokens: String ) {
          registerWorkflowConfig(payload: $payload, metadata: $metadata, tokens: $tokens) {
            identifier
            name
            eventType
            ackSeq
            status
            message
          }
        }
        """
        payload_json = payload if payload is not None else None
        metadata_json = metadata if metadata is not None else None

        variables = {
            "payload": payload_json,
            "metadata": metadata_json,
            "tokens": tokens,
        }
        return {
            "query": mutation,
            "variables": variables
        }


def noetl_api(mutation, tokens, metadata=None, payload=None):
    if payload is None:
        payload = {"message": "empty payload"}
    if metadata is None:
        metadata = {"message": "empty metadata"}
    logger.info(f"tokens: {tokens}, metadata: {metadata}, payload: {payload}")
    try:
        response = requests.post(
            "http://localhost:8021/noetl",
            json=GraphqlMutation.register_workflow_config(payload=payload, metadata=metadata, tokens=tokens)
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


def is_api_running():
    try:
        response = requests.get("http://localhost:8021/health")
        if response.status_code == 200:
            return True
    except Exception as e:
        logger.info(f"NoETL API is not healthy: {str(e)}.")
    return False


def validate_command(command):
    if not is_api_running:
        logger.error("NoETL API not responding")
        raise
    pattern = re.compile(r'^register workflow config file (.+)$', re.IGNORECASE)
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
            "request": "api.request.register_workflow_config"
        }
        payload = {
            "workflow_config_base64": encoded_config
        }

        response = noetl_api(mutation="registerWorkflowConfig", tokens="register workflow config file", metadata=metadata,
                             payload=payload)
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
        result = noetl_api(mutation="spellcheck", tokens=command, metadata=metadata, payload=payload)
        if result is not None:
            logger.info(result)
        else:
            logger.info("NoETL API is not responding.")


def main():
    """
    python noetl/cli.py register workflow config file "workflows/time/get-current-time.yaml"
    :return:
    """
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
