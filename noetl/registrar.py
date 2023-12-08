import asyncio
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig, NatsStreamReference


class Registrar(Plugin):

    async def workflow_register(self,
                                payload_data: Payload,
                                nats_reference: NatsStreamReference
                                ):
        payload_reference = payload_data.get_payload_reference()
        key = payload_data.get_value("metadata.workflow_name")
        payload_kv_value = Payload.kv(
            payload_data={
                "value": payload_data.get_value("workflow_base64"),
                "metadata": payload_data.get_value("metadata") | {"value_type": "base64"}
            },
            nats_pool=await self.get_nats_pool()
        )
        revision_number = await self.workflow_put(key=key, value=payload_kv_value.encode())
        payload: Payload = Payload.create(
            payload_data={
                "revision_number": revision_number,
                "workflow_base64": payload_data.get_value("workflow_base64"),
                "metadata": payload_data.get_value("metadata", exclude=list("command_type")) |
                            {"nats_reference": nats_reference.to_dict(), "event_type": "WorkflowRegistered"}
            },
            origin=payload_reference.get("origin"),
            reference=payload_reference.get("identifier"),
            nats_pool=await self.get_nats_pool()
        )
        ack = await payload.event_write(
            subject=f"registrar.{payload.get_subject_ref()}",
            message=payload.encode()
        )
        logger.debug(ack)

    async def plugin_register(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):
        payload_reference = payload_data.get_payload_reference()
        key = payload_data.get_value("plugin_name")
        payload_kv_value = Payload.kv(
            {
                "value": {
                    "plugin_name": payload_data.get_value("plugin_name"),
                    "image_url": payload_data.get_value("image_url")
                },
                "metadata": payload_data.get_value("metadata") | {"value_type": "dict"}
            }
        )
        revision_number = await self.plugin_put(key=key, value=payload_kv_value.encode())
        payload: Payload = Payload.create(
            payload_data={
                "revision_number": revision_number,
                "plugin_name": payload_data.get_value("plugin_name"),
                "metadata": payload_data.get_value("metadata", exclude=list(["event_type", "command_type"])) |
                            {"nats_reference": nats_reference.to_dict(), "event_type": "PluginRegistered"}
            },
            origin=payload_reference.get("origin"),
            reference=payload_reference.get("identifier"),
            nats_pool=await self.get_nats_pool()
        )
        ack = await payload.event_write(
            subject=f"registrar.{payload.get_subject_ref()}",
            message=payload.encode()
        )
        logger.debug(ack)

    async def run_workflow_register(
            self,
            payload_data: Payload,
            nats_reference: NatsStreamReference
    ):
        payload_reference = payload_data.get_payload_reference()
        key = payload_data.get_value("workflow_name")
        workflow_kv_payload = Payload.decode(await self.workflow_get(key))
        workflow_template = workflow_kv_payload.get_value("value", "WORKFLOW NOT FOUND")
        if workflow_template == "WORKFLOW NOT FOUND":
            payload: Payload = Payload.create(
                payload_data={
                    "error": f"Workflow template {key} was not found",
                    "metadata": payload_data.get_value("metadata", exclude=list(["command_type", "event_type"])) |
                                {"nats_reference": nats_reference.to_dict(),
                                 "event_type": "RunWorkflowRegistrationFailed"}
                },
                origin=payload_reference.get("origin"),
                reference=payload_reference.get("identifier"),
                nats_pool=await self.get_nats_pool()
            )
            ack = await payload.event_write(
                subject=f"dispatcher.{payload.get_subject_ref()}",
                message=payload.encode()
            )
            logger.debug(ack)
        else:
            payload: Payload = Payload.create(
                payload_data={
                    "workflow_template": workflow_template,
                    "workflow_input": payload_data.get_value("workflow_input"),
                    "workflow_metadata": workflow_kv_payload.get_value("metadata", "METADATA NOT FOUND"),
                    "metadata": payload_data.get_value("metadata", exclude=list(["command_type", "event_type"])) |
                        { "nats_reference": nats_reference.to_dict(), "event_type": "RunWorkflowRegistered" }
                },
                origin=payload_reference.get("origin"),
                reference=payload_reference.get("identifier"),
                nats_pool=await self.get_nats_pool()
            )
            ack = await payload.event_write(
                subject=f"dispatcher.{payload.get_subject_ref()}",
                message=payload.encode()
            )
            logger.debug(ack)

    async def switch(self,
                     payload: Payload,
                     nats_reference: NatsStreamReference
                     ):
        match payload.get_value("metadata.command_type"):
            case "RegisterWorkflow":
                await self.workflow_register(payload_data=payload, nats_reference=nats_reference)
            case "RegisterPlugin":
                await self.plugin_register(payload_data=payload, nats_reference=nats_reference)
            case "RegisterRunWorkflow":
                await self.run_workflow_register(payload_data=payload, nats_reference=nats_reference)


if __name__ == "__main__":
    args = parse_args(
        description="NoETL Registrar Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9092
    )
    registrar_plugin = Registrar()
    registrar_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(registrar_plugin.run(args=args, subject_prefix="command.registrar"))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logger.info(f"Dispatcher plugin error: {str(e)}.")
    finally:
        loop.run_until_complete(registrar_plugin.shutdown())
