from keyval import KeyVal
from natstream import NatsConnectionPool, NatsConfig
from payload import Payload


class Playbook(Payload):
    def __init__(
            self,
            playbook_template: dict,
            playbook_id: str,
            playbook_input: dict | None = None,
            playbook_metadata: dict | None = None,
            nats_pool: NatsConnectionPool | NatsConfig = None, **kwargs):
        super().__init__(
            playbook_template=playbook_template,
            playbook_id=playbook_id,
            playbook_input=playbook_input,
            playbook_metadata=playbook_metadata,
            nats_pool=nats_pool, **kwargs)

    async def register(self):
        playbook_data = KeyVal(self.get_value("playbook_template"))
        playbook_data.set_value("spec.id", self.get_value("playbook_id"))
        playbook_data.set_value("spec.input", self.get_value("playbook_input"))
        playbook_data.set_value("spec.kv.metadata", self.get_value("playbook_metadata"))
        subject = f"playbook.{self.get_value('playbook_id')}"
        await self.event_write(
            message=playbook_data.encode(),
            subject=subject
        )
        return subject

    async def generate_command(self):
        pass
