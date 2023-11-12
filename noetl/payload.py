import json
import base64
from loguru import logger
import uuid
from datetime import datetime
import yaml


class Payload(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @classmethod
    def create(cls, payload_data, prefix=None, reference=None):
        payload = cls(payload_data)
        payload.set_identifier(prefix=prefix, reference=reference)
        return payload

    @classmethod
    def kv(cls, payload_data):
        return cls(payload_data)

    def set_identifier(self, prefix=None, reference=None):
        def prefix_path(key: str):
            return ".".join(filter(None, [prefix, key]))

        self.set_value(prefix_path(key="timestamp"), int(datetime.now().timestamp() * 1000))
        identifier = str(uuid.uuid4())
        reference = reference or identifier
        self.set_value(prefix_path(key="identifier"), identifier)
        self.set_value(prefix_path(key="reference"), reference)

    def encode(self):
        try:
            return base64.b64encode(json.dumps(self).encode('utf-8'))
        except Exception as e:
            logger.error(f"Error encoding payload: {str(e)}")
            return None

    @classmethod
    def decode(cls, encoded_payload):
        try:
            return cls(json.loads(base64.b64decode(encoded_payload).decode('utf-8')))
        except Exception as e:
            logger.error(f"Error decoding payload: {str(e)}")
            return None

    def get_keys(self) -> list:
        return list(self.keys())

    def get_value(self, path: str = None, default: any = None):
        try:
            value = self
            if path is None:
                return value
            for key in path.split("."):
                if not isinstance(value, dict):
                    logger.error(f"Value for path segment '{key}' is not a dict.")
                    return default
                value = value.get(key)
                if value is None:
                    logger.warning(f"No value found for path: {path}")
                    return default
            return value
        except Exception as e:
            logger.error(f"Error getting value for path '{path}': {e}")
            return default

    def set_value(self, path: str, value):
        try:
            keys = path.split(".")
            target = self
            for key in keys[:-1]:
                if key not in target or not isinstance(target[key], dict):
                    target[key] = {}
                target = target[key]
            target[keys[-1]] = value
        except Exception as e:
            logger.error(f"Error setting value for path '{path}': {e}")

    def get_base64_yaml(self, path="workflow_base64"):
        return yaml.safe_load(base64.b64decode(self.get_value(f"{path}").encode()).decode())

    @classmethod
    def workflow_create(cls, payload_data, metadata, tokens, event_type):
        try:
            workflow_template = cls(**payload_data)
            decoded_workflow = workflow_template.get_base64_yaml(path="workflow_base64").get("metadata")
            name = decoded_workflow.get("name")
            if name:
                metadata = metadata or {}
                workflow_template.set_value("metadata", metadata | {
                    "workflow_name": name,
                    "tokens": tokens
                })
                workflow_template.set_value("event_type", event_type)
                workflow_template.set_identifier("metadata")
                return workflow_template
            else:
                raise ValueError("Workflow name is missing in payload data.")
        except Exception as e:
            logger.error(f"NoETL API failed to create workflow template: {str(e)}.")
