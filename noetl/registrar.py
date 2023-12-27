import asyncio
from plugin import Plugin, parse_args, Namespace, logger, NatsConfig, NatsStreamReference
from payload import Payload, AppKey, CommandType, Metadata, EventType
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
                AppKey.METADATA: payload_data.get_value(AppKey.METADATA, exclude=list([AppKey.EVENT_TYPE, AppKey.COMMAND_TYPE])) |
                            {AppKey.NATS_REFERENCE: nats_reference.to_dict(), AppKey.EVENT_TYPE: EventType.PLAYBOOK_REGISTERED}
            },
            subject_prefix=f"{args.nats_event_prefix}.{AppKey.DISPATCHER}",
            stream=args.nats_subscription_stream)

    async def plugin_register(self,
                              payload_data: Payload,
                              nats_reference: NatsStreamReference,
                              args: Namespace):
        payload_kv_value = Payload.kv(
            payload_data={
                AppKey.VALUE: {
                    AppKey.PLUGIN_NAME: payload_data.get_value(AppKey.PLUGIN_NAME),
                    AppKey.IMAGE_URL: payload_data.get_value(AppKey.IMAGE_URL)
                },
                AppKey.METADATA: payload_data.get_value(AppKey.METADATA) | {AppKey.VALUE_TYPE: AppKey.DICT}
            },
            nats_pool=await self.get_nats_pool()
        )
        revision_number = await self.plugin_put(key=payload_data.get_value(AppKey.PLUGIN_NAME),
                                                value=payload_kv_value.encode())
        await self.publish_event(
            payload_orig=payload_data,
            payload_data={
                AppKey.REVISION_NUMBER: revision_number,
                AppKey.PLUGIN_NAME: payload_data.get_value(AppKey.PLUGIN_NAME),
                AppKey.METADATA: payload_data.get_value(AppKey.METADATA, exclude=list([AppKey.EVENT_TYPE, AppKey.COMMAND_TYPE])) | {
                    AppKey.NATS_REFERENCE: nats_reference.to_dict(), AppKey.EVENT_TYPE: EventType.PLUGIN_REGISTERED}
            },
            subject_prefix=f"{args.nats_event_prefix}.{AppKey.DISPATCHER}",
            stream=args.nats_subscription_stream)

    async def run_playbook_register(self,
                                    payload_data: Payload,
                                    nats_reference: NatsStreamReference,
                                    args: Namespace):
        key = payload_data.get_value(AppKey.PLAYBOOK_NAME, default=AppKey.VALUE_NOT_FOUND)
        playbook_kv_payload = Payload.decode(await self.playbook_get(key))
        playbook_template = playbook_kv_payload.yaml_value(AppKey.VALUE)
        if playbook_template == AppKey.VALUE_NOT_FOUND:
            await self.publish_event(
                payload_orig=payload_data,
                payload_data={
                    AppKey.ERROR: f"Playbook template {key} was not found",
                    AppKey.METADATA: payload_data.get_value(AppKey.METADATA, exclude=list([AppKey.COMMAND_TYPE, AppKey.EVENT_TYPE])) |
                                {AppKey.NATS_REFERENCE: nats_reference.to_dict(),
                                 AppKey.EVENT_TYPE: EventType.RUN_PLAYBOOK_REGISTRATION_FAILED}
                },
                subject_prefix=f"{args.nats_command_prefix}.{AppKey.DISPATCHER}",
                stream=args.nats_subscription_stream)
        else:
            playbook = Playbook(
                playbook_template=playbook_template,
                playbook_input=payload_data.get_value(AppKey.PLAYBOOK_INPUT),
                playbook_metadata=playbook_kv_payload.get_value(AppKey.METADATA, default=AppKey.METADATA_NOT_FOUND),
                playbook_id=payload_data.get_origin_id(),
                nats_pool=self.nats_pool
            )
            playbook_reference = await playbook.register(
                subject=f"{args.nats_event_prefix}.{AppKey.DISPATCHER}",
                stream=args.nats_subscription_stream)
            await self.publish_event(
                payload_orig=payload_data,
                payload_data={
                    AppKey.PLAYBOOK_REFERENCE: playbook_reference,
                    AppKey.PLAYBOOK_METADATA: playbook_kv_payload.get_value(AppKey.METADATA, default=AppKey.METADATA_NOT_FOUND),
                    AppKey.METADATA: payload_data.get_value(AppKey.METADATA, exclude=list([AppKey.COMMAND_TYPE, AppKey.EVENT_TYPE])) |
                                {AppKey.NATS_REFERENCE: nats_reference.to_dict(), AppKey.EVENT_TYPE: EventType.RUN_PLAYBOOK_REGISTERED}
                },
                subject_prefix=f"{args.nats_event_prefix}.{AppKey.DISPATCHER}",
                stream=args.nats_subscription_stream)

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
            case CommandType.REGISTER_RUN_PLAYBOOK:
                await self.run_playbook_register(
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
