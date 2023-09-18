import unittest
from config import Config
from event_store import EventStore, Event
import uuid
import os


class TestConfig(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.event_store = EventStore("test_data")
        self.workflow_instance_id = f"workflow-test-events-{uuid.uuid4()}"

        self.sample_config = {
            "apiVersion": "workflow.noetl.io/v1",
            "kind": "Workflow",
            "metadata": {
                "name": "create-artifact-repository"
            },
            "spec": {
                "vars": {
                    "GCP_PROJECT_ID": "tradetrend",
                    "GCP_REGION": "us-west1",
                    "REPOSITORY_NAME": "test",
                    "INITIAL_TASK": "check-repository"
                },
                "timeout": 60,
                "schedule": "*/5 * * * *",
                "initialSettings": {
                    "start": "{{ spec.vars.INITIAL_TASK }}",
                    "state": "ready"
                },
                "transitions": {
                    "ready": "running",
                    "running": "completed, failed, terminated"
                },
                "tasks": [
                    {
                        "name": "check-repository",
                        "steps": [
                            {
                                "name": "check-repo-exists",
                                "description": "Check if the repository exists",
                                "type": "shell",
                                "command": "gcloud",
                                "args": [
                                    "artifacts",
                                    "repositories",
                                    "describe",
                                    "{{ spec.vars.REPOSITORY_NAME }}",
                                    "--location={{ spec.vars.GCP_REGION }}",
                                    "--project={{ spec.vars.GCP_PROJECT_ID }}"
                                ],
                                "exitCode": 0
                            }
                        ],
                        "switch": [
                            {
                                "next": ["create-repository"],
                                "condition": "{{ tasks.check-repository.steps.check-repo-exists.exitCode }} != 0"
                            },
                            {
                                "next": [],
                                "condition": "{{ tasks.check-repository.steps.check-repo-exists.exitCode }} == 0"
                            }
                        ]
                    },
                    {
                        "name": "create-repository",
                        "steps": [
                            {
                                "name": "create-repo",
                                "description": "Create the repository",
                                "type": "shell",
                                "command": "gcloud",
                                "args": [
                                    "artifacts",
                                    "repositories",
                                    "create",
                                    "{{ vars.REPOSITORY_NAME }}",
                                    "--repository-format=docker",
                                    "--location={{ vars.GCP_REGION }}",
                                    "--project={{ vars.GCP_PROJECT_ID }}"
                                ]
                            }
                        ]
                    }
                ]
            }
        }

        self.config = Config(self.sample_config)

    async def asyncTearDown(self):
        # Clean up test data directory
        test_data_dir = "test_data"
        for filename in os.listdir(test_data_dir):
            file_path = os.path.join(test_data_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

    def test_get_keys(self):
        keys = self.config.get_keys()
        expected_keys = ["apiVersion", "kind", "metadata", "spec"]
        self.assertEqual(keys, expected_keys)

    def test_get_value(self):
        value = self.config.get_value("metadata.name")
        expected_value = "create-artifact-repository"
        self.assertEqual(value, expected_value)

    async def test_evaluate(self):
        event_id = f"{self.workflow_instance_id}.task1.step1.output"
        event = Event(event_id=event_id, event_type="step_output", payload={"exitCode": "failed"})
        print("\nTesting Event's lookup")
        print(self.workflow_instance_id)
        await self.event_store.publish(self.workflow_instance_id, event)
        retrieved_event = await self.event_store.lookup(event.event_id)
        print(retrieved_event)
        input_string = "{{spec.initialSettings.start}} sdfagsdf {{ spec.vars.REPOSITORY_NAME }} and {{data.task1.step1.output.exitCode}}"
        placeholder_value = await self.config.evaluate(input_string, event_store=self.event_store,
                                                       instance_id=self.workflow_instance_id)
        print(placeholder_value)
        expected_result = "check-repository sdfagsdf test and failed"
        self.assertEqual(placeholder_value, expected_result)


if __name__ == '__main__':
    unittest.main()
