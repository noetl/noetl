import sys
import requests
import os
from loguru import logger
from keyval import KeyVal

CWD = os.getcwd()
CSD = os.path.dirname(os.path.abspath(__file__))
API_URL = os.getenv('NOETL_API_URL', "http://localhost:8021/noetl")


class TokenCommand(KeyVal):
    def __init__(self, tokens=None, handler=None, **kwargs):
        super().__init__(**kwargs)
        self.tokens = tokens
        self.handler = handler

    def execute(self):
        mutation = {
            "query": self.create_gql(),
            "variables": self.get_value("variables")
        }
        graphql_request(mutation)

    def create_gql(self):
        match self.handler:
            case "register_workflow":
                return """
                        mutation RegisterWorkflow($workflowBase64: String!, $metadata: JSON, $tokens: String) {
                            registerWorkflow(workflowBase64: $workflowBase64, metadata: $metadata, tokens: $tokens) {
                                identifier
                                name
                                eventType
                                ackSeq
                                status
                                message
                            }
                        }
                        """
            case "register_plugin":
                return """
                mutation RegisterPlugin($pluginName: String!, $imageUrl: String!, $metadata: JSON, $tokens: String) {
                  registerPlugin(pluginName: $pluginName, imageUrl: $imageUrl, metadata: $metadata, tokens: $tokens) {
                    identifier
                    name
                    eventType
                    ackSeq
                    status
                    message
                  }
                }
                """
            case "list_workflows":
                return """
                query ListWorkflows {
                    listWorkflows
                }
                """
            case "delete_events":
                return """
                mutation DeleteEvents {
                    deleteEvents {
                        message
                    }
                }
                """
            case "delete_commands":
                return """
                mutation DeleteCommands {
                    deleteCommands {
                        message
                    }
                }
                """
            case "describe_workflow":
                return """
                query DescribeWorkflow($workflowName: String!) {
                    describeWorkflow(workflowName: $workflowName)
                }
                """
            case _:
                raise NotImplementedError(f"Mutation for tokens '{self.tokens}' does not exists.")

    @classmethod
    def create(cls, tokens):
        logger.info(tokens)
        tokens_list = tokens.split(" ")
        if tokens_list[0].lower() == "exit":
            logger.info("\nGoodbye...")
            sys.exit()
        elif len(tokens_list) > 1:
            handler = f"{tokens_list[0]}_{tokens_list[1]}"
            args = tokens_list[2:]
            match handler:
                case "register_workflow":
                    with open(args[0], 'r') as file:
                        return cls(
                            tokens=tokens,
                            handler=handler,
                            variables={
                                "workflowBase64": cls.base64_str(file.read()),
                                "metadata": {"source": "noetl-cli", "handler": handler},
                                "tokens": tokens
                            }
                        )
                case "register_plugin":
                    if len(args) == 2:
                        return cls(
                            tokens=tokens,
                            handler=handler,
                            variables={
                                "pluginName": args[0], "imageUrl": args[1],
                                "metadata": {"source": "noetl-cli", "handler": handler},
                                "tokens": tokens
                            }
                        )
                case "list_workflows":
                    return cls(
                        payload={},
                        metadata={},
                        tokens="list workflows",
                        handler="list_workflows"
                    )
                case "describe_workflow":
                    if len(args) == 1:
                        return cls(
                            variables={"workflowName": args[0]},
                            tokens="describe workflow",
                            handler="describe_workflow"
                        )
                case "delete_events":
                    return cls(
                        payload={},
                        metadata={},
                        tokens="delete_events",
                        handler="delete_events"
                    )
                case "delete_commands":
                    return cls(
                        payload={},
                        metadata={},
                        tokens="delete commands",
                        handler="delete_commands"
                    )
        raise ValueError(f"Unknown command: {tokens}")


def graphql_request(mutation):
    try:
        response = requests.post(API_URL, json=mutation)
        response.raise_for_status()
        print(response.json())
    except requests.exceptions.RequestException as e:
        logger.error(f"API request error: {e}")
        return None


def is_api_running():
    try:
        response = requests.get(f"{API_URL}/health")
        return response.status_code == 200
    except requests.exceptions.RequestException as e:
        logger.error(f"NoETL API health check failed: {e}")
        return False


def main():
    """
    NoETL command line interface.
    Usage:
      - To register a workflow: python noetl/cli.py register workflow "<path_to_workflow_yaml>"
      - To register a plugin: python noetl/cli.py register plugin "<plugin_name>" "<image_url>"
      - To exit the CLI: Type 'exit' when prompted for a command.
    The NoETL CLI supports registering workflows and plugins by sending GraphQL mutations to the NoETL API endpoint.
    Set the NoETL API endpoint with an environment variable, e.g., NOETL_API_URL="http://localhost:8021/noetl".
    """
    try:
        if len(sys.argv) > 1:
            TokenCommand.create(" ".join(sys.argv[1:])).execute()
        else:
            logger.info("NoETL command line terminal.\nEnter a <command> or 'exit' to quit")
            while True:
                TokenCommand.create(input("> ").lstrip()).execute()

    except KeyboardInterrupt:
        TokenCommand.create("exit").execute()
    except Exception as e:
        logger.info(f"NoETL cli error: {str(e)}.")


if __name__ == "__main__":
    main()
