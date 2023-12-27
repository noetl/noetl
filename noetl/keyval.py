import base64
import yaml
import json
from appkey import AppKey, Metadata, Reference, EventType, CommandType



class KeyVal(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_keys(self, path=None) -> list:
        paths = []
        base = self.get_value(path) if path else self
        if isinstance(base, dict):
            for k in base.keys():
                key_path = f"{path}.{k}" if path else k
                paths.append(key_path)
        return paths

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

    def get_keyval(self, path: str = None, default: any = None, exclude: list[str] = None):
        value = self.get_value(path, default, exclude)
        return KeyVal(value) if isinstance(value, dict) else value

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
            return json.dumps(self).encode(AppKey.UTF_8)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Error converting to JSON: {e}")

    def base64_path(self, path: str = AppKey.PAYLOAD_BASE64):
        base64_value = self.get_value(path)
        if base64_value is None:
            raise ValueError(f"No base64 string found at {path}")
        if not isinstance(base64_value, str):
            raise TypeError(f"Expected string at '{path}', got {type(base64_value).__name__}")
        return KeyVal.str_base64(base64_value)

    def encode(self):
        json_representation = self.to_json()
        return base64.b64encode(json_representation)

    def base64_value(self, path: str = AppKey.VALUE):
        value = self.get_value(path=path, default=AppKey.VALUE_NOT_FOUND)
        if value is None or value == AppKey.VALUE_NOT_FOUND:
            raise ValueError(f"No value found for key {path}")
        elif isinstance(value, str):
            return self.base64_str(value)
        return value

    def yaml_value(self, path: str = AppKey.VALUE):
        value = self.get_value(path=path, default=AppKey.VALUE_NOT_FOUND)
        if value is None or value == AppKey.VALUE_NOT_FOUND:
            raise ValueError(f"No value found for key {path}")
        elif isinstance(value, str):
            return self.base64_yaml(value)
        return value

    def yaml_value_dump(self, path: str = AppKey.VALUE):
        return self.yaml_dump(self.yaml_value(path = path))

    @classmethod
    def decode(cls, encoded_payload):
        try:
            return cls(json.loads(base64.b64decode(encoded_payload).decode(AppKey.UTF_8)))
        except Exception as e:
            raise ValueError(f"Error decoding payload: {e}")

    @staticmethod
    def yaml_dump(source: dict):
        return yaml.safe_dump(source, sort_keys=False, allow_unicode=True)

    @staticmethod
    def str_base64(source: str):
        return base64.b64encode(source.encode()).decode(AppKey.UTF_8)

    @staticmethod
    def base64_str(source: str):
        return base64.b64decode(source.encode()).decode(AppKey.UTF_8)

    @staticmethod
    def base64_yaml(source: str):
        try:
            return yaml.safe_load(base64.b64decode(source.encode()).decode(AppKey.UTF_8))
        except yaml.YAMLError as e:
            raise ValueError(f"Error decoding YAML from base64: {e}")

    @classmethod
    def from_json(cls, json_value: str):
        try:
            data = json.loads(json_value)
            return cls(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error loading from JSON: {e}")
