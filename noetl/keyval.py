import base64
import json
import yaml
from typing import Any, List, Optional, Union
from noetl.common import SafeEncoder


class KeyVal(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._info: Optional[Any] = None

    @staticmethod
    def builder() -> 'KeyValBuilder':
        return KeyValBuilder()

    @property
    def info(self) -> Optional[Any]:
        return self._info

    @info.setter
    def info(self, value: Any):
        self._info = value

    def get_keys(self, path: Optional[str] = None) -> List[str]:
        base = self.get_value(path) if path else self
        if not isinstance(base, dict):
            return []
        return [f"{path}.{k}" if path else k for k in base.keys()]

    def get_value(self, path: Optional[str] = None, default: Any = None, exclude: Optional[List[str]] = None) -> Any:
        exclude = exclude or []

        def prune(obj: Any) -> Any:
            if isinstance(obj, dict):
                return {k: prune(v) for k, v in obj.items() if k not in exclude}
            if isinstance(obj, list):
                return [prune(v) for v in obj]
            return obj

        target = self
        if path:
            for key in path.split("."):
                if isinstance(target, dict):
                    target = target.get(key)
                elif hasattr(target, key):
                    target = getattr(target, key)
                else:
                    return default
                if target is None:
                    return default

        return prune(target)

    def set_value(self, path: str, value: Any):
        if not path:
            raise ValueError("Path cannot be None or empty.")

        keys = path.split(".")
        target = self
        for key in keys[:-1]:
            target = target.setdefault(key, {})

        if isinstance(value, dict) and isinstance(target.get(keys[-1]), dict):
            target[keys[-1]].update(value)
        else:
            target[keys[-1]] = value

    def delete_value(self, path: str):
        keys = path.split(".")
        current = self
        for key in keys[:-1]:
            current = current.get(key)
            if current is None:
                return  # Path does not exist
        current.pop(keys[-1], None)

    def delete_keys(self, keys: List[str]):
        for key in keys:
            self.delete_value(key)

    def retain_keys(self, keys: List[str]):
        existing = set(self.get_keys())
        for key in existing - set(keys):
            self.delete_value(key)

    def add(self, path: str, value: Any) -> 'KeyVal':
        self.set_value(path, value)
        return self

    def to_json(self) -> bytes:
        return json.dumps(self.get_value(), cls=SafeEncoder).encode('utf-8')

    def as_json(self, path: Optional[str] = None, indent: Optional[int] = None) -> str:
        value = self.get_value(path)
        if value is None:
            raise ValueError(f"Invalid path: {path}")
        return json.dumps(value, indent=indent, cls=SafeEncoder)

    def get_keyval(self, path: Optional[str] = None, default: Any = None, exclude: Optional[List[str]] = None) -> Union['KeyVal', Any]:
        value = self.get_value(path, default, exclude)
        return KeyVal(value) if isinstance(value, dict) else value

    def encode(self, keys: Optional[List[str]] = None) -> bytes:
        if keys:
            data = {k: self.get_value(k) for k in keys if self.get_value(k) is not None}
        else:
            data = self.get_value()
        return base64.b64encode(json.dumps(data, cls=SafeEncoder).encode('utf-8'))

    @classmethod
    def decode(cls, encoded_payload: bytes) -> 'KeyVal':
        try:
            payload = base64.b64decode(encoded_payload).decode('utf-8')
            return cls(**json.loads(payload))
        except (ValueError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to decode payload: {e}.")

    @staticmethod
    def str_to_base64(source: str) -> str:
        return base64.b64encode(source.encode('utf-8')).decode('utf-8')

    @staticmethod
    def base64_to_str(source: str) -> str:
        return base64.b64decode(source.encode('utf-8')).decode('utf-8')

    @staticmethod
    def base64_to_yaml(source: str) -> Any:
        try:
            decoded = KeyVal.base64_to_str(source)
            return yaml.safe_load(decoded)
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to decode YAML: {e}.")

    @staticmethod
    def yaml_dump(source: dict) -> str:
        return yaml.safe_dump(source, sort_keys=False, allow_unicode=True)

    def base64_value(self, path: str = "value") -> str:
        value = self.get_value(path, "valueNotFound")
        if value in (None, "valueNotFound"):
            raise ValueError(f"Value not found for path: {path}.")
        if isinstance(value, str):
            return self.base64_str(value)
        raise TypeError(f"Expected string at path '{path}', got {type(value).__name__}.")

    def base64_str(self, source: str) -> str:
        return KeyVal.str_to_base64(source)

    def yaml_value(self, path: str = "value") -> Any:
        value = self.get_value(path, "valueNotFound")
        if isinstance(value, str) and value not in ("valueNotFound", None):
            return KeyVal.base64_to_yaml(value)
        return value

    def yaml_value_dump(self, path: str = "value") -> str:
        return KeyVal.yaml_dump(self.yaml_value(path))


class KeyValBuilder:
    def __init__(self):
        self._store = KeyVal()

    def add(self, path: str, value: Any) -> 'KeyValBuilder':
        self._store.set_value(path, value)
        return self

    def remove(self, path: str) -> 'KeyValBuilder':
        self._store.delete_value(path)
        return self

    def info(self, metadata: Any) -> 'KeyValBuilder':
        self._store.info = metadata
        return self

    def build(self) -> KeyVal:
        return self._store


if __name__ == "__main__":
    def check_keyval_builder():
        payload = (
            KeyVal.builder()
            .add("user.name", "Kadyapam")
            .add("user.age", 52)
            .add("account.active", True)
            .info({"created_by": "Maidu people"})
            .build()
        )
        print("Account info:", payload.get_keys("account"))
        print("User info:", payload.get_keys("user"))
        print("User name:", payload.get_value("user.name"))
        print("User age:", payload.get_value("user.age"))
        print("Account active:", payload.get_value("account.active"))
        print("Account info:", payload.get_value("account.info"))
        print("Metadata info:", payload.get_value("info"))
        print("Encoded payload:", payload.encode(["user.name", "user.age"]))
        print("Decoded payload:", KeyVal.decode(payload.encode(["user.name", "user.age"])))
        print("Encoded full payload:", payload.encode())
        print("Metadata info:", payload.info)
    check_keyval_builder()