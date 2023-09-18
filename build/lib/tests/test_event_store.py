import unittest
import os
import uuid
from event_store import EventStore, Event


class TestEventStore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.event_store = EventStore("test_data")
        self.workflow_instance_id = f"workflow-test-events-{uuid.uuid4()}"

    # async def asyncTearDown(self):
    #     # Clean up test data directory
    #     test_data_dir = "test_data"
    #     for filename in os.listdir(test_data_dir):
    #         file_path = os.path.join(test_data_dir, filename)
    #         if os.path.isfile(file_path):
    #             os.remove(file_path)

    async def test_store_and_retrieve_event(self):
        event = Event(event_id="test_instance", event_type="task_status", payload={"status": "completed"})

        await self.event_store.publish(self.workflow_instance_id, event)

        retrieved_payload = await self.event_store.lookup(event.event_id)

        self.assertEqual(retrieved_payload.payload, event.payload)

    async def test_get_event(self):
        event = Event(event_id="event_id_2", event_type="task_status", payload={"status": "failed"})

        await self.event_store.publish(self.workflow_instance_id, event)

        retrieved_event = await self.event_store.lookup(event.event_id)

        self.assertEqual(retrieved_event.payload, event.payload)

    async def test_reload_events(self):
        event = Event(event_id="event_id_3", event_type="task_status", payload={"status": "in_progress"})

        await self.event_store.publish(self.workflow_instance_id, event)

        await self.event_store.reload_events(self.workflow_instance_id)

        retrieved_event = await self.event_store.lookup(event.event_id)

        self.assertEqual(retrieved_event.payload, event.payload)


if __name__ == "__main__":
    unittest.main()
