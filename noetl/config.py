import re
import yaml
import sys
from loguru import logger
from dataclasses import dataclass
from event_store import EventStore, Event


async def get_path_value(object_value, path):
    keys = path.split(".")
    current_value = object_value
    for key in keys:
        current_value = current_value.get(key)
        if current_value is None:
            return ""
    return current_value


@dataclass
class EventStorePath:
    event_store_key: str | None
    payload_key: str | None
    payload: dict | None  # TODO need to clarify datatype
    event_store: EventStore | None

    def __init__(self, path: str, instance_id: str = None, event_store: EventStore = None):
        self.event_store_key, self.payload_key = self.parse_path(path, instance_id)
        self.event_store = event_store

    def __repr__(self):
        return f"EventStorePath(event_store_key='{self.event_store_key}', payload_key='{self.payload_key}', data='{self.payload}')"

    def parse_path(self, path: str, instance_id: str):
        if path.startswith("data."):
            path = path.replace("data.", f"{instance_id}.", 1)

            if path.endswith(".output"):
                return path, None

            if ".output." in path:
                event_store_key, payload_key = path.split(".output.", 1)
                event_store_key = f"{event_store_key}.output"
                return event_store_key, payload_key

        return None, None

    async def get_payload(self):
        event = await self.event_store.lookup(self.event_store_key)
        if isinstance(event, Event):
            self.payload = event.payload
            if self.payload and self.payload_key:
                data = await get_path_value(self.payload, self.payload_key)
                if data:
                    return data
            else:
                return self.payload
        logger.error(f"Error: Key '{self.event_store_key}' not found in event_store")
        return f"Error: Key '{self.event_store_key}' not found in event_store"

    @classmethod
    def create(cls, path: str, instance_id: str, event_store: EventStore = None):
        event_store_path = cls(path, instance_id, event_store)
        if not event_store_path.event_store_key:
            return None
        if all(value is None for value in (
                event_store_path.event_store_key,
                event_store_path.event_store
        )
               ):
            logger.error(
                f"Error: Key '{event_store_path.event_store_key}' event_store must be provided")
            return f"Error: Key '{event_store_path.event_store_key}' event_store must be provided"
        return event_store_path


class Config(dict):
    def __init__(self, *args, **kwargs):
        super(Config, self).__init__(*args, **kwargs)

    def get_keys(self) -> list:
        return list(self.keys())

    def get_value(self, path: str = None):
        try:
            value = self
            if path is None:
                return value
            keys = path.split(".")
            for key in keys:
                value = value.get(key)
                if value is None:
                    return None
            return value
        except Exception as e:
            logger.error(e)

    async def get_async(self, path: str = None, event_store=None, instance_id=None):
        try:
            value = self
            if path is None:
                result = await self.evaluate(value, event_store, instance_id)
                return result
            keys = path.split(".")
            for key in keys:
                value = value.get(key)
                if value is None:
                    return None
            result = await self.evaluate(value, event_store, instance_id)
            return result
        except Exception as e:
            logger.error(e)

    def set_value(self, path: str, value):
        try:
            keys = path.split(".")
            target = self
            for key in keys[:-1]:
                target = target.setdefault(key, {})
            target[keys[-1]] = value
        except Exception as e:
            logger.error(e)

    async def evaluate(self, input_value, event_store=None, instance_id=None):
        async def get_match(match):
            query_path = match.group(1)
            event_store_data = EventStorePath.create(
                path=query_path,
                instance_id=instance_id,
                event_store=event_store
            )
            if event_store_data:
                return await event_store_data.get_payload()
            value = await get_path_value(self, query_path)
            return await replace_placeholders(value)

        async def replace_placeholders(value):
            if isinstance(value, (list, tuple, set, frozenset, dict)):
                if isinstance(value, dict):
                    return {key: await replace_placeholders(val) for key, val in value.items()}
                return [await replace_placeholders(item) for item in value]
            elif isinstance(value, str):
                return await replace_matches(value)
            return value

        async def replace_matches(input_string):
            matches = re.finditer(r"{{\s*(.*?)\s*}}", input_string)
            replacement_result = input_string
            for match in matches:
                replacement = await get_match(match)
                if replacement is not None:
                    replacement_result = replacement_result.replace(match.group(0), str(replacement))
            return replacement_result

        result = await replace_placeholders(input_value)
        return result

    def update_vars(self):
        args_dict = self.parse_args()
        logger.info(args_dict)
        for k, v in args_dict.items():
            self.set_value(f"spec.vars.{k}", v)

    @staticmethod
    def parse_args():
        custom_args = {}
        for arg in sys.argv[1:]:
            if '=' in arg:
                key, value = arg.split('=')
                custom_args[key] = value
        return custom_args

    @classmethod
    def create(cls):
        if len(sys.argv) < 2 or not sys.argv[1].startswith("CONFIG="):
            print("Usage: python noetl/noetl.py CONFIG=/path/to/config")
            sys.exit(1)

        config_path = sys.argv[1].split('=')[1]
        with open(config_path, 'r') as file:
            config = yaml.safe_load(file)
            return cls(config)
