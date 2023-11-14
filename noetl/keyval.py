import base64
from loguru import logger
import yaml
import json


class KeyVal(dict):
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

    def to_json(self):
        try:
            return json.dumps(self).encode('utf-8')
        except Exception as e:
            logger.error(f"Error dumping to JSON: {e}")
            return None

    def base64_path(self, path="workflow_base64"):
        base64_value = str(self.get_value(path))
        if base64_value is None:
            logger.error(f"No base64 string found at path: {path}")
            return None
        try:
            return KeyVal.base64_str(base64_value)
        except Exception as e:
            logger.error(f"Error decoding and loading YAML from base64 at path '{path}': {e}")
            return None

    def encode(self):
        try:
            return base64.b64encode(self.to_json())
        except Exception as e:
            logger.error(f"Error encoding payload: {str(e)}")
            return None

    def yaml_value(self):
        return yaml.safe_load(base64.b64decode(self.get_value("value").encode()).decode('utf-8'))

    @classmethod
    def decode(cls, encoded_payload):
        try:
            return cls(json.loads(base64.b64decode(encoded_payload).decode('utf-8')))
        except Exception as e:
            logger.error(f"Error decoding payload: {str(e)}")
            return None

    @staticmethod
    def base64_str(source: str):
        return base64.b64encode(source.encode()).decode('utf-8')

    @staticmethod
    def base64_yaml(source: str):
        return yaml.safe_load(base64.b64decode(source.encode()).decode('utf-8'))

    @classmethod
    def from_json(cls, json_value: str):
        try:
            data = json.loads(json_value)
            return cls(data)
        except Exception as e:
            logger.error(f"Error loading from JSON: {e}")
            return None
