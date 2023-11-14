from loguru import logger
import uuid
from datetime import datetime
from keyval import KeyVal


class Payload(KeyVal):

    def set_identifier(self, prefix=None, reference=None):
        def prefix_path(key: str):
            return ".".join(filter(None, [prefix, key]))

        self.set_value(prefix_path(key="timestamp"), int(datetime.now().timestamp() * 1000))
        identifier = str(uuid.uuid4())
        reference = reference or identifier
        self.set_value(prefix_path(key="identifier"), identifier)
        self.set_value(prefix_path(key="reference"), reference)

    def set_event_type(self, event_type):
        self.set_value("event_type", event_type)

    def set_command_type(self, command_type):
        self.set_value("command_type", command_type)

    def set_origin_ref(self, origin_ref):
        self.set_value("origin_ref", origin_ref)

    @classmethod
    def create(cls, payload_data, origin_ref=None, prefix=None, reference=None, event_type=None, command_type=None):
        payload = cls(payload_data)

        payload.set_identifier(prefix=prefix, reference=reference)
        if origin_ref:
            payload.set_origin_ref(origin_ref)
        else:
            payload.set_origin_ref(payload.get_value(f"{prefix}.identifier"))
        if event_type:
            payload.set_event_type(event_type)
        if command_type:
            payload.set_command_type(command_type)
        return payload

    @classmethod
    def kv(cls, payload_data):
        return cls(payload_data)

    @classmethod
    def workflow_create(cls, workflow_base64, metadata, tokens, event_type):
        try:
            name = cls.base64_yaml(workflow_base64).get("metadata").get("name")
            if name:
                return cls.create(
                    payload_data={
                        "workflow_base64": workflow_base64,
                        "metadata": metadata | {
                            "workflow_name": name,
                            "tokens": tokens
                        }
                    },
                    prefix="metadata",
                    event_type=event_type

                )
            else:
                raise ValueError("Workflow name is missing in the YAML.")
        except Exception as e:
            logger.error(f"NoETL API failed to create workflow template: {str(e)}.")
