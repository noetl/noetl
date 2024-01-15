import argparse
import sys
from loguru import logger
from noetl.natstream import NatsConfig
from dataclasses import dataclass
import os
from strawberry.fastapi import BaseContext

@dataclass
class AppConfig(BaseContext):
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
    nats_subscription_subject: str
    nats_subscription_stream: str
    nats_subscription_queue: str
    nats_command_prefix: str
    nats_command_stream: str
    nats_event_prefix: str
    nats_event_stream: str

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
        parser.add_argument("--nats_url", default=os.getenv("NATS_URL", "nats://localhost:32222"),
                            help="nats://<host>:<port>")
        parser.add_argument("--nats_pool_size", type=int, default=int(os.getenv("NATS_POOL_SIZE", 10)),
                            help="NATS max pool size (default: 10)")
        parser.add_argument("--nats_subscription_subject",
                            default=os.getenv('NATS_SUBSCRIPTION_SUBJECT', "noetl"),
                            help="NATS subject for subscription")
        parser.add_argument("--nats_subscription_stream",
                            default=os.getenv('NATS_SUBSCRIPTION_STREAM', "noetl"),
                            help="NATS subscription stream")
        parser.add_argument("--nats_subscription_queue",
                            default=os.getenv('NATS_SUBSCRIPTION_QUEUE', "noetl-api"),
                            help="NATS JetStream subscription group queue")
        parser.add_argument("--nats_command_prefix",
                            default=os.getenv('NATS_COMMAND_PREFIX', "noetl.command"),
                            help="NATS subject prefix for commands")
        parser.add_argument("--nats_command_stream",
                            default=os.getenv('NATS_COMMAND_STREAM', "noetl"),
                            help="NATS JetStream name for commands")
        parser.add_argument("--nats_event_prefix",
                            default=os.getenv('NATS_EVENT_PREFIX', "noetl.event"),
                            help="NATS subject prefix for events")
        parser.add_argument("--nats_event_stream",
                            default=os.getenv('NATS_EVENT_STREAM', "noetl"),
                            help="NATS JetStream name for events")

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
            limit_max_requests=args.limit_max_requests,
            nats_subscription_subject=args.nats_subscription_subject,
            nats_subscription_stream=args.nats_subscription_stream,
            nats_subscription_queue=args.nats_subscription_queue,
            nats_command_prefix=args.nats_command_prefix,
            nats_command_stream=args.nats_command_stream,
            nats_event_prefix=args.nats_event_prefix,
            nats_event_stream=args.nats_event_stream
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
