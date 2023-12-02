import asyncio
from plugin import Plugin, parse_args
from payload import Payload
from loguru import logger
from natstream import NatsConfig, NatsStreamReference


class ShellHandler(Plugin):

    async def execute_shell_command(self,
                                    payload_data: Payload,
                                    nats_reference: NatsStreamReference
                                    ):
        payload_reference = payload_data.get_payload_reference()

        command = payload_data.get_value("command")
        origin_ref = payload_data.get_value("origin_ref")
        process = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            text=True
        )

        stdout, stderr = await process.communicate()

        response_payload = Payload.create(
            payload_data={
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": process.returncode
            },
            origin_ref=origin_ref,
            nats_pool=await self.get_nats_pool()
        )

        await self.event_write(subject=f"shell-handler.output.{origin_ref}", message=response_payload.encode())

    async def switch(self, payload: Payload, nats_reference: NatsStreamReference):
        if payload.get_value("command_type") == "ShellCommand":
            await self.execute_shell_command(payload, nats_reference)


if __name__ == "__main__":
    args = parse_args(
        description="Shell Handler Plugin",
        default_nats_url="nats://localhost:32222",
        default_nats_pool_size=10,
        default_prom_host="localhost",
        default_prom_port=9094
    )
    shell_handler_plugin = ShellHandler()
    shell_handler_plugin.initialize_nats_pool(NatsConfig(
        nats_url=args.nats_url,
        nats_pool_size=args.nats_pool_size
    ))
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(shell_handler_plugin.run(args=args, subject_prefix="command.shell-handler"))
    except KeyboardInterrupt:
        sys.exit()
    except Exception as e:
        logger.error(f"Shell Handler plugin error: {str(e)}")
