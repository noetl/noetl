import argparse
import asyncio
import socket
from loguru import logger
from dataclasses import dataclass
from natstream import NatsConnectionPool
from aioprometheus import Counter
from aioprometheus.service import Service
from record import Record, RecordField


@dataclass
class Command:
    events_counter: Counter
    nats_pool: NatsConnectionPool
    records: list[Record] | None = None

    @classmethod
    def create(cls, args):
        return cls(
            events_counter=Counter("commander_events", "Number of events.", const_labels={"host": socket.gethostname()}),
            nats_pool=NatsConnectionPool(args.nats_url, 10)
        )


    async def add_wrokflow_catalog(self, record: Record):
        async with self.nats_pool.connection() as nc:
            workflow_catalog = await nc.create_key_value(bucket="workflow_catalog")
            try:
                await workflow_catalog.delete(record.name.value)
                await workflow_catalog.put(record.name.value, record.payload.serialize())
                entry = await workflow_catalog.get(record.name.value)
                logger.debug(entry)
                entry_value = RecordField.deserialize(entry.value)
                logger.info(f"KeyValue.Entry: key={entry.key}, value={entry_value}")
            except Exception as e:
                print(f"Bucket does not exist: {e}")
    async def api_add_workflow(self, record: Record):
        logger.debug(f"{record}")
        await self.add_wrokflow_catalog(record=record)

    def default_command(self):
        logger.error(f"No Command handler implemented yet")
        return f"No Command handler implemented yet"
    async def switch(self, value):
        command=value.metadata.value.get("command")
        method_name = command.replace('.', '_')
        method = getattr(self, method_name, self.default_command)
        return await method(value)

    async def handle_command(self, msg):
        logger.info(msg)
        command_data = Record.deserialize(msg.data)
        _= await self.switch(command_data)
        logger.info(command_data)

        # event = f"Processed {command}"
        # logger.info(event)
        # # Create a Record instance
        # record = Record.create(
        #     name='CommandEvent',
        #     kind='TASK',
        #     reference=None,
        #     metadata={'command': command},
        #     payload={'event': event}
        # )
        # # Serialize the record
        # serialized_record = record.serialize()
        #
        # # Publish event
        # async with self.nats_pool.connection() as nc:
        #     await nc.publish('events', serialized_record)
        # # Increment events counter
        # events_counter.inc({"kind": "command_processed"})

    async def nats_subscribe(self):
        async with self.nats_pool.connection() as nc:
            await nc.subscribe("command.api.>", cb=self.handle_command)
            while True:
                await asyncio.sleep(1)




async def main(args):
    logger.info(args)
    service = Service()
    await service.start(addr=args.prom_host, port=args.prom_port)
    logger.info(f"Serving prometheus metrics on: {service.metrics_url}")
    command_handler = Command.create(args)
    _ = await command_handler.nats_subscribe()



def parse_args():
    parser = argparse.ArgumentParser(description="NoETL Commander Service")
    parser.add_argument("--nats_url", default="nats://localhost:4222", help="NATS server URL")
    parser.add_argument("--prom_host", default='127.0.0.1', help="Prometheus host")
    parser.add_argument("--prom_port", type=int, default=8000, help="Prometheus port")
    return parser.parse_args()


if __name__ == "__main__":
    try:
        asyncio.run(main(args=parse_args()))
    except KeyboardInterrupt:
        pass
