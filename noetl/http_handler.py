import asyncio
from plugin import Plugin, Payload, PayloadReference, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
import aiohttp


class HttpHandler(Plugin):
    async def http_request(self,
                           payload_data: Payload,
                           nats_reference: NatsStreamReference,
                           args: Namespace):
        url = payload_data.get_value("url")
        method = payload_data.get_value("method")
        data = payload_data.get_value("data")
        payload_reference: PayloadReference = PayloadReference(**payload_data.get_payload_reference())
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, data=data) as response:
                response_data = await response.text()

        await self.publish_event(
            payload_orig=payload_data,
            payload_data={
                 "response": response_data,
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) |
                            {"nats_reference": nats_reference.to_dict(), "event_type": "HTTPRequestEstebleshed"}
            },
            subject_prefix=f"{args.nats_command_prefix}.dispatcher",
            stream=args.nats_subscription_stream)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference,
                     args: Namespace
                     ):
        match payload.get_value("metadata.event_type"):
            case "HttpRequest":
                await self.http_request(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)


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
