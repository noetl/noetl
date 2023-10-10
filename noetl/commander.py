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
class CommandHander:
    events_counter: Counter
    nats_pool: NatsConnectionPool
    records: list[Record] | None = None

    @classmethod
    def create(cls, args):
        return cls(
            events_counter=Counter("commander_events", "Number of events.", const_labels={"host": socket.gethostname()}),
            nats_pool=NatsConnectionPool(args.nats_url, 10)
        )

    async def handle_command(self, msg):
        logger.info(msg)
        command = Record.deserialize(msg.data)
        logger.info(command)
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
    command_handler = CommandHander.create(args)
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
