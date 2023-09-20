import unittest
import os
import uuid
from store import Store
from event import Event, EventType


class TestEventStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Store("test_data")
        self.workflow_instance_id = f"workflow-test-events-{uuid.uuid4()}"

    async def asyncTearDown(self):
        test_data_dir = "test_data"
        for filename in os.listdir(test_data_dir):
            file_path = os.path.join(test_data_dir, filename)
            if os.path.isfile(file_path):
                os.remove(file_path)

    async def test_store_and_retrieve_event(self):
        event = await self.store.publish_event(
            instance_id="test_instance",
            event_type=EventType.WORKFLOW_STARTED,
            payload={"status": "completed"}
        )

        retrieved_payload = await self.store.lookup(event.event_id)

        self.assertEqual(retrieved_payload.payload, event.payload)

    async def test_get_event(self):
        event = await self.store.publish_event(instance_id="test_instance",
                                               event_type=EventType.TASK_STATE,
                                               payload={"status": "failed"}
                                               )

        retrieved_event = await self.store.lookup(event.event_id)

        self.assertEqual(retrieved_event.payload, event.payload)

    async def test_reload_events(self):

        event = await self.store.publish_event(instance_id="test_instance",
                                               event_type="task_status",
                                               payload={"status": "in_progress"}
                                               )

        await self.store.reload_events(self.workflow_instance_id)

        retrieved_event = await self.store.lookup(event.event_id)

        self.assertEqual(retrieved_event.payload, event.payload)


if __name__ == "__main__":
    unittest.main()
