from noetl.natstream import NatsConnectionPool, NatsConfig
from payload import Payload


class Workflow(Payload):
    def __init__(self, payload_data, nats_pool: NatsConnectionPool | NatsConfig = None, **kwargs):
        super().__init__(payload_data, nats_pool=nats_pool, **kwargs)
        self.workflow_template = None

    async def transit(self):
        self.workflow_template = self.yaml_value(path="workflow_base64")

    async def generate_command(self):
        pass
