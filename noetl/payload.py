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
    def create(cls, payload_data):
        payload = cls(payload_data)
        payload.set_identifier()
        return payload

    @classmethod
    def create_workflow(cls, payload_data, metadata, tokens, event_type):
        try:
            encoded_workflow = base64.b64decode(payload_data.get("workflow_base64").encode()).decode()
            workflow_template = cls({"workflow_template": yaml.safe_load(encoded_workflow)})
            workflow_template.set_value("name", workflow_template.get_value("workflow_template.metadata.name"))
            metadata = metadata or {}
            workflow_template.set_value("metadata", metadata | {"event_type": event_type, "tokens": tokens})
            workflow_template.set_identifier("metadata.")
            logger.debug(workflow_template)
            return workflow_template
        except Exception as e:
            logger.error(f"NoETL API failed to create workflow template: {str(e)}.")

    def set_identifier(self, prefix=""):
        self.set_value(f"{prefix}timestamp", int(datetime.now().timestamp() * 1000))
        identifier = str(uuid.uuid4())
        self.set_value(f"{prefix}identifier", identifier)
        self.set_value(f"{prefix}reference", self.get("reference", identifier))

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

    def get_value(self, path: str = None):
        try:
            value = self
            if path is None:
                return value
            for key in path.split("."):
                if not isinstance(value, dict):
                    logger.error(f"Value for path segment '{key}' is not a dict.")
                    return None
                value = value.get(key)
                if value is None:
                    logger.warning(f"No value found for path: {path}")
                    return None
            return value
        except Exception as e:
            logger.error(f"Error getting value for path '{path}': {e}")
            return None

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
