import base64
import yaml
import json
from noetl.const import AppConst


class KeyVal(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._info: any = None

    @property
    def info(self):
        return self._info

    @info.setter
    def info(self, value: any):
        self._info = value

    def get_keys(self, path=None) -> list:
        paths = []
        base = self.get_value(path) if path else self
        if isinstance(base, dict):
            for k in base.keys():
                key_path = f"{path}.{k}" if path else k
                paths.append(key_path)
        return paths

    def get_value(self, path: str = None, default: any = None, exclude: list[str] = None):
        exclude = exclude if exclude else []

        def to_dict(obj):
            if isinstance(obj, dict):
                return {k: to_dict(v) for k, v in obj.items() if k not in exclude}
            elif isinstance(obj, list):
                return [to_dict(v) for v in obj]
            else:
                return obj

        if path is None:
            value = to_dict(self)
            return value

        try:
            value = self
            for key in path.split("."):
                if isinstance(value, dict):
                    value = value.get(key)
                elif hasattr(value, key):
                    value = getattr(value, key)
                else:
                    raise TypeError(f"Value for '{key}' is not a dict or does not have attribute '{key}'")
                value = to_dict(value)
                if value is None:
                    return default
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

            if isinstance(value, dict) and isinstance(target.get(keys[-1]), dict):
                target[keys[-1]].update(value)
            else:
                target[keys[-1]] = value
        except Exception as e:
            raise ValueError(f"Error setting value for '{path}': {e}")

    def delete_value(self, path: str):
        keys = path.split('.')
        current_key = keys.pop()
        current_dict = self
        for key in keys:
            if key in current_dict:
                current_dict = current_dict[key]
            else:
                return
        if current_key in current_dict:
            del current_dict[current_key]

    def delete_keys(self, keys=None):
        if keys:
            candidates = [k for k in self.get_keys() if k in keys]
            for key in candidates:
                self.delete_value(key)

    def retain_keys(self, keys=None):
        if keys:
            self.delete_keys(keys=[k for k in self.get_keys() if k not in keys])

    def to_json(self):
        try:
            return json.dumps(self.get_value()).encode(AppConst.UTF_8)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Error converting to JSON: {e}")

    def base64_path(self, path: str = AppConst.PAYLOAD_BASE64):
        base64_value = self.get_value(path)
        if base64_value is None:
            raise ValueError(f"No base64 string found at {path}")
        if not isinstance(base64_value, str):
            raise TypeError(f"Expected string at '{path}', got {type(base64_value).__name__}")
        return KeyVal.str_base64(base64_value)

    def encode(self, keys=None):
        return base64.b64encode(
            json.dumps(self if keys is None else {key: self[key] for key in keys if key in self.get_value()}).encode(
                AppConst.UTF_8))

    def base64_value(self, path: str = AppConst.VALUE):
        value = self.get_value(path=path, default=AppConst.VALUE_NOT_FOUND)
        if value is None or value == AppConst.VALUE_NOT_FOUND:
            raise ValueError(f"No value found for key {path}")
        elif isinstance(value, str):
            return self.base64_str(value)
        return value

    def yaml_value(self, path: str = AppConst.VALUE):
        value = self.get_value(path=path, default=AppConst.VALUE_NOT_FOUND)
        if isinstance(value, str) and value not in [AppConst.VALUE_NOT_FOUND, None]:
            return self.base64_yaml(value)
        return value

    def yaml_value_dump(self, path: str = AppConst.VALUE):
        return self.yaml_dump(self.yaml_value(path=path))

    @classmethod
    def decode(cls, encoded_payload):
        try:
            payload_data = json.loads(base64.b64decode(encoded_payload).decode(AppConst.UTF_8))
            return cls(**payload_data)
            # return cls(json.loads(base64.b64decode(encoded_payload).decode(AppConst.UTF_8)))
        except Exception as e:
            raise ValueError(f"Error decoding payload: {e}")

    @staticmethod
    def yaml_dump(source: dict):
        return yaml.safe_dump(source, sort_keys=False, allow_unicode=True)

    @staticmethod
    def str_base64(source: str):
        return base64.b64encode(source.encode()).decode(AppConst.UTF_8)

    @staticmethod
    def base64_str(source: str):
        return base64.b64decode(source.encode()).decode(AppConst.UTF_8)

    @staticmethod
    def base64_yaml(source: str):
        try:
            return yaml.safe_load(base64.b64decode(source.encode()).decode(AppConst.UTF_8))
        except yaml.YAMLError as e:
            raise ValueError(f"Error decoding YAML from base64: {e}")

    @classmethod
    def from_json(cls, json_value: str):
        try:
            data = json.loads(json_value)
            return cls(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Error loading from JSON: {e}")
