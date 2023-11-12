import asyncio
import sys
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig, NatsStreamReference


class Registrar(Plugin):

    async def workflow_register(self,
                                payload_data: Payload,
                                nats_reference: NatsStreamReference
                                ):
        key = payload_data.get_value("metadata.workflow_name")
        payload_kv_value = Payload.kv(
            {
                "value": payload_data.get_value("workflow_base64"),
                "metadata": payload_data.get_value("metadata") | {"value_type": "base64"}
            }
        )
        revision_number = await self.workflow_put(key=key, value=payload_kv_value.encode())
        payload = Payload.create(
            payload_data={
                "revision_number": revision_number,
                "metadata": payload_data.get_value("metadata") | nats_reference.to_dict(),
                "event_type": "WorkflowRegistered"
            },
            prefix="metadata",
            reference=payload_data.get_value("metadata.identifier")
        )
        logger.debug(payload)

        await self.event_write(
            subject=f"registrar.{payload.get_value('metadata.identifier')}",
            message=payload.encode()
        )

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference
                     ):
        if payload.get_value("command_type") == "RegisterWorkflow":
            await self.workflow_register(payload_data=payload, nats_reference=nats_reference)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Registrar Service",
        default_nats_url="nats://localhost:32645",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9092
    )
    try:
        registrar = Registrar.create(NatsConfig(nats_url=args.nats_url, nats_pool_size=args.nats_pool_size))
        asyncio.run(registrar.run(args, subject_prefix="command.registrar"))
    except KeyboardInterrupt:
        sys.exit()
    except Exception as e:
        logger.info(f"Dispatcher error: {str(e)}.")
