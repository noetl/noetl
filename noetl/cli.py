import sys
import requests
import os
import json
import yaml
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
        if self.handler in ['show_events', 'show_commands']:
            self.graphql_query()
        else:
            mutation = {
                "query": self.create_gql(),
                "variables": self.get_value("variables", {})
            }
            graphql_request(mutation)

    def graphql_query(self):
        query_info = {
            "query": self.create_gql()
        }
        response = requests.post(API_URL, json=query_info)
        if response.status_code == 200:
            print(json.dumps(response.json(), indent=2))
        else:
            print(f"Request failed with status code {response.status_code}")

    def create_gql(self):
        match self.handler:
            case "show_events":
                return """
                query showEvents{
                    showEvents
                }
                    """
            case "show_commands":
                return """
                query showCommands{
                    showCommands
                }
                    """
            case "register_playbook":
                return """
                        mutation RegisterPlaybook($playbookBase64: String!, $metadata: JSON, $tokens: String) {
                            registerPlaybook(playbookBase64: $playbookBase64, metadata: $metadata, tokens: $tokens) {
                                reference 
                                name
                                eventType
                                status
                                message
                            }
                        }
                        """
            case "register_plugin":
                return """
                        mutation RegisterPlugin($registrationInput: PluginRegistrationInput!) {
                          registerPlugin(registrationInput: $registrationInput) {
                            reference 
                            name
                            eventType
                            status
                            message
                          }
                        }
                """
            case "list_playbooks":
                return """
                query ListPlaybooks {
                    listPlaybooks
                }
                """
            case "list_plugins":
                return """
                query ListPlugins {
                    listPlugins
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
            case "describe_playbook":
                return """
                query DescribePlaybook($playbookInput: DescribePlaybookInput!) {
                  describePlaybook(playbookInput: $playbookInput)
                }
                """
            case "describe_plugin":
                return """
                query DescribePlugin($pluginInput: DescribePluginInput!) {
                  describePlugin(pluginInput: $pluginInput)
                }
                """
            case "run_playbook":
                return """
                query RunPlaybook($runPlaybookInput: RunPlaybookInput!) {
                  runPlaybook(runPlaybookInput: $runPlaybookInput) {
                    reference
                    name
                    eventType
                    status
                    message
                  }
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
                case "register_playbook":
                    with open(args[0], 'r') as file:
                        return cls(
                            tokens=tokens,
                            handler=handler,
                            variables={
                                "playbookBase64": cls.str_base64(file.read()),
                                "metadata": {"source": "noetl-cli", "handler": handler},
                                "tokens": tokens
                            }
                        )
                case "register_plugin":
                    if len(args) == 2:
                        return cls(
                            tokens=tokens,
                            handler=handler,
                            variables={"registrationInput":
                                {
                                    "pluginName": args[0], "imageUrl": args[1],
                                    "metadata": {"source": "noetl-cli", "handler": handler},
                                    "tokens": tokens
                                }
                            }
                        )
                case "list_playbooks":
                    return cls(
                        tokens=tokens,
                        handler=handler
                    )
                case "list_plugins":
                    return cls(
                        tokens=tokens,
                        handler=handler
                    )
                case "describe_playbook":
                    if len(args) == 1:
                        return cls(
                            variables={"playbookInput": {"playbookName": args[0]}},
                            tokens="describe playbook",
                            handler="describe_playbook"
                        )
                case "run_playbook":
                    if len(args) >= 2:
                        try:
                            playbook_input = json.loads(args[1])
                            playbook_input_json = json.dumps(playbook_input)
                        except json.JSONDecodeError:
                            raise ValueError("Invalid JSON for playbookInput")

                        return cls(
                            variables={"runPlaybookInput":
                                           {"playbookName": args[0],
                                            "input": playbook_input_json
                                            }
                                       },
                            tokens="run playbook",
                            handler="run_playbook"
                        )
                    else:
                        raise ValueError("Need playbookName, playbookInput arguments to run playbook")
                case "describe_plugin":
                    if len(args) == 1:
                        return cls(
                            variables={"pluginInput": {"pluginName": args[0]}},
                            tokens="describe plugin",
                            handler="describe_plugin"
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
                case "show_events":
                    return cls(
                        tokens=tokens,
                        handler=handler,
                    )
                case "show_commands":
                    return cls(
                        tokens=tokens,
                        handler=handler,
                    )
        raise ValueError(f"Unknown command: {tokens}")


def graphql_request(mutation):
    try:
        response = requests.post(API_URL, json=mutation)
        response.raise_for_status()
        if response.ok:
            if "describePlaybook" in response.json().get('data', {}):
                response_keyval = KeyVal(response.json())
                print(response_keyval.base64_value("data.describePlaybook.playbook.playbookBase64"))
            else:
                print(json.dumps(response.json(), indent=2))
        else:
            print(response)
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
      - To register a playbook: python noetl/cli.py register playbook "<path_to_playbook_yaml>"
      - To register a plugin: python noetl/cli.py register plugin "<plugin_name>" "<image_url>"
      - To exit the CLI: Type 'exit' when prompted for a command.
    The NoETL CLI supports registering playbooks and plugins by sending GraphQL mutations to the NoETL API endpoint.
    Set the NoETL API endpoint with an environment variable, e.g., NOETL_API_URL="http://localhost:8021/noetl".
    """
    try:
        if len(sys.argv) > 1:
            TokenCommand.create(" ".join(sys.argv[1:])).execute()
        else:
            logger.info("NoETL command line terminal.\nEnter a <command> or 'exit' to quit")
            while True:
                line = input("> ").lstrip()
                if line.lower() == "exit":
                    logger.info("\nGoodbye...")
                    break
                try:
                    TokenCommand.create(line).execute()
                except ValueError as e:
                    logger.error(f"Invalid command: {e}")
                except FileNotFoundError:
                    logger.error(f"File not found")
                except NotImplementedError as e:
                    logger.error(f"Not implemented: {e}")

    except KeyboardInterrupt:
        logger.info("\nGoodbye...")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")


if __name__ == "__main__":
    main()
