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
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_plugin_name="http-handler:0_1_0",
        default_nats_subscription_subject="noetl.event.http-handler:0_1_0.>",
        default_nats_subscription_stream="noetl",
        default_nats_subscription_queue="noetl-http-handler-0-1-0",
        default_nats_command_prefix="noetl.command",
        default_nats_command_stream="noetl",
        default_nats_event_prefix="noetl.event",
        default_nats_event_stream="noetl",
        default_prom_host="localhost",
        default_prom_port=9093
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
