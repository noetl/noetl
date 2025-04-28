from datetime import datetime
import json

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
