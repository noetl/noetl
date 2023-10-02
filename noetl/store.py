import os
import json
import aiofiles
import threading
from event import Event
from loguru import logger


class Store:
    def __init__(self, data_dir: str = "noetldb"):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.in_memory_store = {}
        self.lock = threading.Lock()

    async def publish_event(self, instance_id, event_type, payload, metadata=None):
        try:
            event_id = f"{instance_id}.{event_type.as_str()}"
            event = Event.create(event_id=event_id, event_type=event_type, payload=payload, metadata=metadata)
            logger.info(event)
            return await self.publish(event=event)
        except Exception as e:
            logger.error(f"Error: {e}\n instance_id: {instance_id}\n event_type: {event_type.as_str}\n payload: {payload}\n metadata: {metadata} ")
        return

    async def publish(self, event: Event):
        with self.lock:
            await self.file_save(event=event)
            if event.event_id not in self.in_memory_store:
                self.in_memory_store[event.event_id] = event
            return event

    async def lookup(self, event_id: str):
        with self.lock:
            return self.in_memory_store.get(event_id, None)

    async def get_store_path(self, workflow_instance_id):
        return os.path.join(self.data_dir, f"{workflow_instance_id}.noetl")

    async def file_save(self, event: Event):
        async with aiofiles.open(await self.get_store_path(event.get_workflow_id()), 'a') as file:
            await file.write(json.dumps(event.as_dict()) + '\n')

    async def reload_events(self, workflow_id):
        events = []
        async with aiofiles.open(await self.get_store_path(workflow_id), 'r') as file:
            self.in_memory_store = {}
            async for line in file:
                event = Event.from_dict(json.loads(line))
                if event is not None:
                    with self.lock:
                        self.in_memory_store[event.event_id] = event
        logger.info(self.in_memory_store)
