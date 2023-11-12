import argparse
import yaml
import sys
from loguru import logger
import base64
from natstream import NatsConfig
from dataclasses import dataclass
import os


@dataclass
class AppConfig:
    _instance = None
    log_level: str | None
    nats_config: NatsConfig
    env: str | None
    host: str | None
    port: int | None
    reload: bool | None
    workers: int | None
    limit_concurrency: int | None
    limit_max_requests: int | None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(AppConfig, cls).__new__(cls)
        return cls._instance

    @classmethod
    def get_nats_config(cls):
        if cls._instance is None:
            raise Exception("ApiConfig instance was not initialized.")
        return cls._instance.nats_config

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            raise Exception("ApiConfig instance was not initialized.")
        return cls._instance

    @classmethod
    def app_args(cls):
        parser = argparse.ArgumentParser(description="NoETL API")
        parser.add_argument("--env", default=os.getenv("ENV", "local"),
                            help="Environment (default: local)")
        parser.add_argument("--log_level", default=os.getenv("LOG_LEVEL", "DEBUG"),
                            help="Log level (default: DEBUG)")
        parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"),
                            help="Host to bind (default: 0.0.0.0)")
        parser.add_argument("--port", type=int, default=int(os.getenv("PORT", 8021)),
                            help="Port to listen on (default: 8021)")
        parser.add_argument("--workers", type=int, default=int(os.getenv("WORKERS", 1)),
                            help="Number of workers (default: 1)")
        parser.add_argument("--reload", action='store_true', help="Enable auto-reload (default: disabled)")
        parser.add_argument("--limit_concurrency", type=int, default=int(os.getenv("MAX_CONCURRENCY", 100)),
                            help="Limit concurrency (default: 100)")
        parser.add_argument("--limit_max_requests", type=int, default=int(os.getenv("MAX_REQUESTS", 100)),
                            help="Limit requests (default: 100)")
        parser.add_argument("--nats_url", default=os.getenv("NATS_URL", "nats://localhost:32645"),
                            help="nats://<host>:<port>")
        parser.add_argument("--nats_pool_size", type=int, default=int(os.getenv("NATS_POOL_SIZE", 10)),
                            help="NATS max pool size (default: 10)")
        args = parser.parse_args()
        return cls(
            nats_config=NatsConfig(nats_url=args.nats_url, nats_pool_size=args.nats_pool_size),
            env=args.env,
            log_level=args.log_level,
            host=args.host,
            port=args.port,
            reload=args.reload,
            workers=args.workers,
            limit_concurrency=args.limit_concurrency,
            limit_max_requests=args.limit_max_requests
        )

    def set_log_level(self):
        if self.log_level == "INFO":
            logger.remove()
            logger.add(sys.stderr, level="INFO")
        elif self.log_level == "DEBUG":
            logger.remove()
            logger.add(sys.stderr, level="DEBUG")
        else:
            logger.remove()
            logger.add(sys.stderr, level="WARNING")

#
#
# class Config(dict):
#     def __init__(self, *args, **kwargs):
#         super(Config, self).__init__(*args, **kwargs)
#
#     def get_keys(self) -> list:
#         return list(self.keys())
#
#     def get_value(self, path: str = None):
#         try:
#             value = self
#             if path is None:
#                 return value
#             keys = path.split(".")
#             for key in keys:
#                 value = value.get(key)
#                 if value is None:
#                     return None
#             return value
#         except Exception as e:
#             logger.error(e)
#
#     async def get_async(self, path: str = None, store=None, instance_id=None):
#         try:
#             value = self
#             if path is None:
#                 result = await self.evaluate(value, store, instance_id)
#                 return result
#             keys = path.split(".")
#             for key in keys:
#                 value = value.get(key)
#                 if value is None:
#                     return None
#             result = await self.evaluate(value, store, instance_id)
#             return result
#         except Exception as e:
#             logger.error(e)
#
#     def set_value(self, path: str, value):
#         try:
#             keys = path.split(".")
#             target = self
#             for key in keys[:-1]:
#                 target = target.setdefault(key, {})
#             target[keys[-1]] = value
#         except Exception as e:
#             logger.error(e)
#
#     # async def evaluate(self, input_value, store: Store=None, instance_id=None):
#     #     async def get_match(match):
#     #         query_path = match.group(1)
#     #         event_store_data = EventStorePath.create(
#     #             path=query_path,
#     #             instance_id=instance_id,
#     #             store=store
#     #         )
#     #         if event_store_data:
#     #             return await event_store_data.get_payload()
#     #         value = await get_path_value(self, query_path)
#     #         return await replace_placeholders(value)
#     #
#     #     async def replace_placeholders(value):
#     #         if isinstance(value, (list, tuple, set, frozenset, dict)):
#     #             if isinstance(value, dict):
#     #                 return {key: await replace_placeholders(val) for key, val in value.items()}
#     #             return [await replace_placeholders(item) for item in value]
#     #         elif isinstance(value, str):
#     #             return await replace_matches(value)
#     #         return value
#     #
#     #     async def replace_matches(input_string):
#     #         matches = re.finditer(r"{{\s*(.*?)\s*}}", input_string)
#     #         replacement_result = input_string
#     #         for match in matches:
#     #             replacement = await get_match(match)
#     #             if replacement is not None:
#     #                 replacement_result = replacement_result.replace(match.group(0), str(replacement))
#     #         return replacement_result
#     #
#     #     result = await replace_placeholders(input_value)
#     #     return result
#
#     def update_vars(self):
#         args_dict = self.parse_args()
#         logger.info(args_dict)
#         for k, v in args_dict.items():
#             self.set_value(f"spec.vars.{k}", v)
#
#     @staticmethod
#     def parse_args():
#         custom_args = {}
#         for arg in sys.argv[1:]:
#             if '=' in arg:
#                 key, value = arg.split('=')
#                 custom_args[key] = value
#         return custom_args
#
#     @classmethod
#     def create_from_file(cls):
#         if len(sys.argv) < 2 or not sys.argv[1].startswith("CONFIG="):
#             print("Usage: python noetl/noetl.py CONFIG=/path/to/config")
#             sys.exit(1)
#
#         config_path = sys.argv[1].split('=')[1]
#         with open(config_path, 'r') as file:
#             config = yaml.safe_load(file)
#             return cls(config)
#
#     @classmethod
#     def create(cls, payload):
#         try:
#             payload_config = base64.b64decode(payload.get("config").encode()).decode()
#             config = yaml.safe_load(payload_config)
#             return cls(config)
#         except Exception as e:
#             logger.error(f"NoETL API failed to create config: {str(e)}.")
#
#     @classmethod
#     def create_workflow(cls, payload):
#         try:
#             payload_config = base64.b64decode(payload.get("workflow_base64").encode()).decode()
#             config = yaml.safe_load(payload_config)
#             return cls(config)
#         except Exception as e:
#             logger.error(f"NoETL API failed to create workflow template: {str(e)}.")
#
#
# async def get_path_value(object_value, path):
#     keys = path.split(".")
#     current_value = object_value
#     for key in keys:
#         current_value = current_value.get(key)
#         if current_value is None:
#             return ""
#     return current_value
#
#
# def parse_path(path: str, instance_id: str):
#     if path.startswith("data."):
#         path = path.replace("data.", f"{instance_id}.", 1)
#
#         if path.endswith(".output"):
#             return path, None
#
#         if ".output." in path:
#             event_store_key, payload_key = path.split(".output.", 1)
#             event_store_key = f"{event_store_key}.output"
#             return event_store_key, payload_key
#
#     return None, None
