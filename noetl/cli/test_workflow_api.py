import requests
import json

url = "http://localhost:8000/graphql"

headers = {"Content-Type": "application/json"}

data = {
    "query": """
    mutation ($workflow: WorkflowInput!) {
        submitWorkflow(workflow: $workflow) {
            success
            message
            workflow {
                id
                metadata {
                    name
                }
                spec {
                    vars {
                        key
                        value
                    }
                    timeout
                    schedule
                    initialSettings {
                        start
                        state
                    }
                    transitions
                    tasks {
                        key
                        task {
                            steps {
                                command {
                                    description
                                    type
                                    command
                                    args
                                }
                                httpRequest {
                                    description
                                    type
                                    method
                                    url
                                    headers {
                                        key
                                        value
                                    }
                                    requestBody
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    """,
    "variables": {
        "workflow": {
            "apiVersion": "workflow.noetl.io/v1",
            "kind": "Workflow",
            "metadata": {"name": "example-workflow"},
            "spec": {
                "vars": [
                    {"key": "message1", "value": "hello"},
                    {"key": "message2", "value": "world"},
                    {"key": "message3", "value": "hello task 2"},
                    {"key": "message4", "value": "hello task 3"},
                    {"key": "message5", "value": "hello task 4"},
                    {"key": "message6", "value": "hello task 5"},
                ],
                "timeout": 60,
                "schedule": "*/5 * * * *",
                "initialSettings": {"start": ["task1", "task3"], "state": "ready"},
                "transitions": {
                    "ready": ["running"],
                    "running": ["idle", "paused", "completed", "failed", "terminated"],
                    "idle": ["running"],
                    "paused": ["running"],
                },
                "tasks": [
                    {
                        "key": "task1",
                        "task": {
                            "steps": [
                                {
                                    "command": {
                                        "description": "hello task 1",
                                        "type": "shell",
                                        "command": "echo",
                                        "args": ["{{ vars.message1 }}", "{{ vars.message2 }}"],
                                    }
                                },
                                {
                                    "httpRequest": {
                                        "description": "hello task 1",
                                        "type": "http",
                                        "method": "post",
                                        "url": "",
                                        "headers": [
                                            {"key": "x-my-header", "value": ""}
                                        ],
                                        "requestBody": '{"application/json": "{\\"{{ vars.message1 }}\\": \\"{{ vars.message2 }}\\"}"}',
                                    }
                                },
                            ]
                        },
                    },
                    {
                        "key": "task2",
                        "task": {
                            "steps": [
                                {
                                    "command": {
                                        "description": "hello task 2",
                                        "type": "shell",
                                        "command": "echo",
                                        "args": ["{{ vars.message3 }}"],
                                    }
                                }
                            ]
                        },
                    },
                    {
                        "key": "task3",
                        "task": {
                            "steps": [
                                {
                                    "command": {
                                        "description": "hello task 3",
                                        "type": "shell",
                                        "command": "echo",
                                        "args": ["{{ vars.message4 }}"],
                                    }
                                }
                            ]
                        },
                    },
                    {
                        "key": "task4",
                        "task": {
                            "steps": [
                                {
                                    "command": {
                                        "description": "hello task 4",
                                        "type": "shell",
                                        "command": "echo",
                                        "args": ["{{ vars.message5 }}"],
                                    }
                                }
                            ]
                        },
                    },
                    {
                        "key": "task5",
                        "task": {
                            "steps": [
                                {
                                    "command": {
                                        "description": "hello task 5",
                                        "type": "shell",
                                        "command": "echo",
                                        "args": ["{{ vars.message6 }}"],
                                    }
                                }
                            ]
                        },
                    },
                ],
            },
        }
    },
}

response = requests.post(url, json=data, headers=headers)

response_json = response.json()
print(json.dumps(response_json, indent=4))
