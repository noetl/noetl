import asyncio
from plugin import Plugin, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
from payload import Payload, PubAck, AppKey, CommandType, Metadata, EventType
from playbook import Playbook


class Registrar(Plugin):

    async def playbook_register(self,
                                payload_data: Payload,
                                nats_reference: NatsStreamReference,
                                args: Namespace):
        payload_kv_value = Payload.kv(
            payload_data={
                AppKey.VALUE: payload_data.get_value(AppKey.PLAYBOOK_BASE64),
                AppKey.METADATA: payload_data.get_value(AppKey.METADATA) | {AppKey.VALUE_TYPE: AppKey.BASE64}
            },
            nats_pool=await self.get_nats_pool()
        )
        revision_number = await self.playbook_put(key=payload_data.get_value(Metadata.PLAYBOOK_NAME),
                                                  value=payload_kv_value.encode())
        await self.publish_event(
            payload_orig=payload_data,
            payload_data={
                AppKey.REVISION_NUMBER: revision_number,
                AppKey.PLAYBOOK_BASE64: payload_data.get_value(AppKey.PLAYBOOK_BASE64),
                AppKey.METADATA: payload_data.get_value(AppKey.METADATA,
                                                        exclude=list([AppKey.EVENT_TYPE, AppKey.COMMAND_TYPE])) |
                                 {AppKey.NATS_REFERENCE: nats_reference.to_dict(),
                                  AppKey.EVENT_TYPE: EventType.PLAYBOOK_REGISTERED}
            },
            subject_prefix=f"{args.nats_event_prefix}.{AppKey.DISPATCHER}",
            stream=args.nats_subscription_stream)

    async def plugin_register(self,
                              payload_data: Payload,
                              nats_reference: NatsStreamReference,
                              args: Namespace):
        await payload_data.plugin_put()
        payload_data.update_reference()
        payload_data.set_metadata(metadata={AppKey.NATS_REFERENCE: nats_reference.to_dict()})
        ack = await payload_data.event_write(
            subject=f"{args.nats_event_prefix}.{AppKey.DISPATCHER}.{payload_data.get_origin_id()}",
            stream=args.nats_subscription_stream,
            message=payload_data.encode(keys=[AppKey.REVISION_NUMBER ,AppKey.PLUGIN_NAME, AppKey.IMAGE_URL, AppKey.METADATA ])
        )

        logger.debug(ack)

    async def register_playbook_execution_request(self,
                                    payload_data: Payload,
                                    nats_reference: NatsStreamReference,
                                    args: Namespace):

        await payload_data.snapshot_playbook(nats_reference=nats_reference.to_dict())

        ack = await payload_data.event_write(
            subject=f"{args.nats_event_prefix}.{AppKey.DISPATCHER}.{payload_data.get_origin_id()}",
            stream=args.nats_subscription_stream,
            message=payload_data.encode()
        )

        logger.debug(ack)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference,
                     args: Namespace):
        match payload.get_value(Metadata.COMMAND_TYPE):
            case CommandType.REGISTER_PLAYBOOK:
                await self.playbook_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)
            case CommandType.REGISTER_PLUGIN:
                await self.plugin_register(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)
            case CommandType.REGISTER_PLAYBOOK_EXECUTION:
                await self.register_playbook_execution_request(
                    payload_data=payload,
                    nats_reference=nats_reference,
                    args=args)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Registrar Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_plugin_name="registrar",
        default_nats_subscription_subject="noetl.command.registrar.>",
        default_nats_subscription_stream="noetl",
        default_nats_subscription_queue="noetl-registrar",
        default_nats_command_prefix="noetl.command",
        default_nats_command_stream="noetl",
        default_nats_event_prefix="noetl.event",
        default_nats_event_stream="noetl",
        default_prom_host="localhost",
        default_prom_port=9091
    )
    registrar_plugin = Registrar()
    registrar_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size,
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(registrar_plugin.run(args=args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"Dispatcher plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(registrar_plugin.shutdown())
