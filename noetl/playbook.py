import uuid
from natstream import NatsConnectionPool, NatsConfig
from payload import Payload, AppConst,  RawStreamMsg


class Playbook(Payload):
    def __init__(self,
                 playbook_template: dict | None = None,
                 playbook_id: str | None = None,
                 playbook_input: dict | None = None,
                 playbook_metadata: dict | None = None,
                 nats_pool: NatsConnectionPool | NatsConfig = None, **kwargs):
        if playbook_template:
            kwargs = kwargs | playbook_template
        super().__init__(nats_pool=nats_pool, **kwargs)
        if playbook_id:
            self.set_value("spec.reference.origin_id", playbook_id)
        if playbook_input:
            self.set_value("spec.input", playbook_input)
        if playbook_metadata:
            self.set_value("metadata.nats.kv.metadata", playbook_metadata)

    # def execution_tree(self):
    #     tasks = self.get_keys(path="spec.tasks")
    #     for task_path in tasks:
    #         task_id = str(uuid.uuid4())
    #         self.set_value(f"{task_path}.id", task_id)
    #
    #         steps = self.get_keys(path=f"{task_path}.steps")
    #         for step_path in steps:
    #             step_id = str(uuid.uuid4())
    #             self.set_value(f"{step_path}.id", step_id)

    async def register(self,subject: str, stream: str):
        #subject = f"playbook.{self.get_value('spec.id')}"
        ack = await self.event_write(
            message=self.encode(),
            stream=stream,
            subject=subject
        )
        return ack

    async def generate_command(self):
        pass


    @classmethod
    def unmarshal(cls, binary_data: bytes, nats_pool: NatsConnectionPool | NatsConfig = None):
        return cls(nats_pool=nats_pool, **cls.decode(binary_data))
