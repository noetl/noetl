import uuid
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
            nats_pool=nats_pool,
            **playbook_template,
            **kwargs)
        self.set_value("spec.id", playbook_id)
        self.set_value("spec.input", playbook_input)
        self.set_value("spec.kv.metadata", playbook_metadata)
        self.add_execution_tree()

    def add_execution_tree(self):
        tasks = self.get_keys(path="spec.tasks")
        for task_path in tasks:
            task_id = str(uuid.uuid4())
            self.set_value(f"{task_path}.id", task_id)

            steps = self.get_keys(path=f"{task_path}.steps")
            for step_path in steps:
                step_id = str(uuid.uuid4())
                self.set_value(f"{step_path}.id", step_id)

    async def register(self):
        subject = f"playbook.{self.get_value('spec.id')}.blueprint"
        await self.event_write(
            message=self.encode(),
            subject=subject
        )
        return subject

    async def generate_command(self):
        pass
