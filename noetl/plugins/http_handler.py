import asyncio
from noetl.plugin import Plugin, Payload, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
import aiohttp


class HttpHandler(Plugin):
    async def http_request(self, payload: Payload):
        url = payload.get_value("url")
        method = payload.get_value("method")
        data = payload.get_value("data")
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, data=data) as response:
                response_data = await response.text()

        # await self.publish_event(
        #     payload_orig=payload,
        #     payload_data={
        #          "response": response_data},
        #     subject_prefix=f"{args.nats_command_prefix}.dispatcher",
        #     stream=args.nats_subscription_stream)

    async def switch(self, payload: Payload):
        match payload.get_value("metadata.event_type"):
            case "HttpRequest":
                await self.http_request(payload=payload)


if __name__ == "__main__":

    args = parse_args(
        description="NoETL HTTPHandler Plugin",
        nats_url=("NATS_URL", "nats://localhost:32222", "NATS server URL"),
        nats_pool_size=("NATS_POLL_SIZE", 10, "NATS pool size"),
        plugin_name=("PLUGIN_NAME", "http-handler:0_1_0", "Plugin name"),
        nats_subscription_subject=("NATS_SUBSCRIPTION_SUBJECT", "noetl.event.http-handler:0_1_0.>", "NATS subject for subscription"),
        nats_subscription_stream=("NATS_SUBSCRIPTION_STREAM", "noetl", "NATS subscription stream"),
        nats_subscription_queue=("NATS_SUBSCRIPTION_QUEUE", "noetl-http-handler-0-1-0", "NATS JetStream subscription group queue"),
        nats_command_prefix=("NATS_COMMAND_PREFIX", "noetl.command", "NATS subject prefix for commands"),
        nats_command_stream=("NATS_COMMAND_STREAM", "noetl", "NATS JetStream name for commands"),
        nats_event_prefix=("NATS_EVENT_PREFIX", "noetl.event", "NATS subject prefix for events"),
        nats_event_stream=("NATS_EVENT_STREAM", "noetl", "NATS JetStream name for events"),
        prom_host=("PROM_HOST", "localhost", "Prometheus host"),
        prom_port=("PROM_PORT", 9093, "Prometheus port")
    )
    http_handler_plugin = HttpHandler()
    http_handler_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(http_handler_plugin.run(args=args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"HttpHandler plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(http_handler_plugin.shutdown())
