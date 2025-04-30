from datetime import datetime
import base64
import json
import yaml
from collections import OrderedDict

def make_serializable(value):
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Exception):
        return str(value)
    if isinstance(value, dict):
        return {k: make_serializable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [make_serializable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {k: make_serializable(v) for k, v in value.__dict__.items()}
    return value


class SafeEncoder(json.JSONEncoder):
    def default(self, obj):
        return None


def ordered_yaml_dump(data):
    def convert_ordered_dict(obj):
        if isinstance(obj, OrderedDict):
            return {k: convert_ordered_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_ordered_dict(i) for i in obj]
        return obj

    cleaned_data = convert_ordered_dict(data)
    return yaml.dump(cleaned_data, default_flow_style=False, sort_keys=False)

def ordered_yaml_load(stream):
    class OrderedLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node):
        loader.flatten_mapping(node)
        return OrderedDict(loader.construct_pairs(node))

    OrderedLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
        construct_mapping
    )
    return yaml.load(stream, OrderedLoader)

def encode_version(version: str) -> str:
    major, minor, patch = map(int, version.split("."))
    return f"{major:03d}.{minor:03d}.{patch:03d}"

def decode_version(encoded_version: str) -> str:
    major, minor, patch = encoded_version.split(".")
    return f"{int(major)}.{int(minor)}.{int(patch)}"

def increment_version(version: str) -> str:
    major, minor, patch = map(int, version.split("."))

    patch += 1
    if patch > 999:
        patch = 0
        minor += 1
        if minor > 999:
            minor = 0
            major += 1
            if major > 999:
                raise ValueError("Version overflow -> version limit is '999.999.999'")

    return f"{major}.{minor}.{patch}"