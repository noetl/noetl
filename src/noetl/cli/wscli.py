import asyncio
import json
import websockets
import yaml


async def connect_websocket():
    # websocket_url = "ws://localhost:8000/graphql"
    websocket_url = "ws://localhost:8000/ws"

    # Command functions
    command_functions = {
        "load workflow": load_workflow,
        "get workflow": get_workflow,
        "start workflow": start_workflow,
        "get list of workflow names": get_workflow_names,
        "get workflow events": get_workflow_events
    }

    async with websockets.connect(websocket_url) as websocket:
        while True:
            user_input = input("> ")

            command_parts = user_input.split(" ", maxsplit=1)
            command = command_parts[0]
            arguments = command_parts[1] if len(command_parts) > 1 else ""

            if command in command_functions:
                await command_functions[command](websocket, arguments)
            else:
                print("Invalid command. Available commands:")
                print("load workflow <path_to_workflow.yaml>")
                print("get workflow <workflow:example-workflow>")
                print("start workflow <workflow_name>")
                print("get list of workflow names")
                print("get workflow events")


async def load_workflow(websocket, path):
    try:
        with open(path, "r") as file:
            workflow_yaml = file.read()

        workflow_data = yaml.safe_load(workflow_yaml)

        mutation = {
            "query": """
                mutation SubmitWorkflow($workflow: WorkflowInput!) {
                    submitWorkflow(workflow: $workflow)
                }
            """,
            "variables": {
                "workflow": workflow_data
            }
        }

        await websocket.send(json.dumps({"type": "start", "payload": mutation}))

        response = await websocket.recv()
        print(response)
    except FileNotFoundError:
        print("File not found.")


async def get_workflow(websocket, workflow_name):
    query = {
        "query": """
            query GetWorkflow($name: String!) {
                workflow(name: $name) {
                    # Specify the fields you want to retrieve
                    name
                    spec {
                        # Specify the subfields you want to retrieve
                        timeout
                        schedule
                        tasks {
                            key
                            task {
                                steps {
                                    command {
                                        type
                                        command
                                        args
                                    }
                                    httpRequest {
                                        method
                                        url
                                    }
                                }
                            }
                        }
                    }
                }
            }
        """,
        "variables": {
            "name": workflow_name
        }
    }

    await websocket.send(json.dumps({"type": "start", "payload": query}))

    response = await websocket.recv()
    print(response)


async def start_workflow(websocket, workflow_name):
    mutation = {
        "query": """
            mutation StartWorkflow($name: String!) {
                startWorkflow(name: $name)
            }
        """,
        "variables": {
            "name": workflow_name
        }
    }

    await websocket.send(json.dumps({"type": "start", "payload": mutation}))

    response = await websocket.recv()
    print(response)


async def get_workflow_names(websocket, _):
    query = {
        "query": """
            query GetWorkflowNames {
                workflowNames
            }
        """
    }

    await websocket.send(json.dumps({"type": "start", "payload": query}))

    response = await websocket.recv()
    print(response)


async def get_workflow_events(websocket, _):
    query = {
        "query": """
            query GetWorkflowEvents {
                workflowEvents {
                    # Specify the fields you want to retrieve
                    timestamp
                    workflowName
                    eventType
                    eventData
                }
            }
        """
    }

    await websocket.send(json.dumps({"type": "start", "payload": query}))

    response = await websocket.recv()
    print(response)


async def main():
    while True:
        command = input("Enter a command: ")
        if command == "connect":
            await connect_websocket()
        elif command == "exit":
            break


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
