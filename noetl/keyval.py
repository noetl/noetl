import base64
import yaml
import json


class KeyVal(dict):
    def get_keys(self) -> list:
        return list(self.keys())

    def get_value(self, path: str = None, default: any = None, exclude: list[str] = None):
        if path is None:
            return self
        try:
            value = self
            for key in path.split("."):
                if not isinstance(value, dict):
                    raise TypeError(f"Value for '{key}' is not a dict.")
                value = value.get(key)
                if value is None:
                    return default
            if exclude and isinstance(value, dict):
                return {key: val for key, val in value.items() if key not in exclude}
            return value
        except Exception as e:
            raise ValueError(f"Error getting value for '{path}': {e}")


    def set_value(self, path: str, value):
        if path is None:
            raise TypeError("Path cannot be None")
        try:
            keys = path.split(".")
            target = self
            for key in keys[:-1]:
                if key not in target or not isinstance(target[key], dict):
                    target[key] = {}
                target = target[key]
            target[keys[-1]] = value
        except Exception as e:
            raise ValueError(f"Error setting value for '{path}': {e}")

    def to_json(self):
        try:
            return json.dumps(self).encode('utf-8')
        except (TypeError, ValueError) as e:
            raise ValueError(f"Error converting to JSON: {e}")

    def base64_path(self, path="workflow_base64"):
        base64_value = self.get_value(path)
        if base64_value is None:
            raise ValueError(f"No base64 string found at {path}")
        if not isinstance(base64_value, str):
            raise TypeError(f"Expected string at '{path}', got {type(base64_value).__name__}")
        return KeyVal.base64_str(base64_value)

    def encode(self):
        json_representation = self.to_json()
        return base64.b64encode(json_representation)

    def yaml_value(self):
        value = self.get_value("value")
        if value is None:
            raise ValueError("No value found for key 'value'")
        return yaml.safe_load(base64.b64decode(value.encode()).decode('utf-8'))

    @classmethod
    def decode(cls, encoded_payload):
        try:
            return cls(json.loads(base64.b64decode(encoded_payload).decode('utf-8')))
        except Exception as e:
            raise ValueError(f"Error decoding payload: {e}")

    @staticmethod
    def base64_str(source: str):
        return base64.b64encode(source.encode()).decode('utf-8')

    @staticmethod
    def base64_yaml(source: str):
        try:
            return yaml.safe_load(base64.b64decode(source.encode()).decode('utf-8'))
        except yaml.YAMLError as e:
            raise ValueError(f"Error decoding YAML from base64: {e}")

    @classmethod
    def from_json(cls, json_value: str):
        try:
            data = json.loads(json_value)
            return cls(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error loading from JSON: {e}")
