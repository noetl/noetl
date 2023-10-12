import argparse
import asyncio
import socket
from natstream import NatsConnectionPool
from aioprometheus import Counter
from aioprometheus.service import Service
from record import Record, RecordField

parser = argparse.ArgumentParser(description='Commander Service')
parser.add_argument('--nats-url', default='nats://localhost:4222', help='NATS server URL')
parser.add_argument('--prom-host', default='127.0.0.1', help='Prometheus host')
parser.add_argument('--prom-port', type=int, default=8000, help='Prometheus port')
args = parser.parse_args()

nats_pool = NatsConnectionPool(args.nats_url, 10)

# Prometheus metrics
events_counter = Counter(
    "events", "Number of events.", const_labels={"host": socket.gethostname()}
)

# ... rest of your code ...

async def main():
    service = Service()
    await service.start(addr=args.prom_host, port=args.prom_port)
    print(f"Serving prometheus metrics on: {service.metrics_url}")

    # ... rest of your code ...

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
