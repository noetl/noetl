import asyncio
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig, NatsStreamReference
import aiohttp
import sys


class HttpHandler(Plugin):

    async def http_request(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):
        url = payload_data.get_value("url")
        method = payload_data.get_value("method")
        data = payload_data.get_value("data")
        origin_ref = payload_data.get_value("origin_ref")
        async with aiohttp.ClientSession() as session:
            async with session.request(method, url, data=data) as response:
                response_data = await response.text()

        response_payload = Payload.create(
            payload_data={"response": response_data},
            origin_ref=payload_data.get_value("origin_ref"),
            prefix="metadata",
            reference=nats_reference.to_dict()
        )
        await self.event_write(subject=f"http-request.output.{origin_ref}", message=response_payload.encode())

    async def switch(self, payload: Payload, nats_reference: NatsStreamReference):
        if payload.get_value("command_type") == "HttpRequest":
            await self.http_request(payload, nats_reference)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL HttpHandler Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9092
    )
    http_handler_plugin = HttpHandler()
    http_handler_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(http_handler_plugin.run(args=args, subject_prefix="command.HttpHandler"))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"HttpHandler plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(http_handler_plugin.shutdown())
