import asyncio
from nats.aio.client import Client as NATS
from nats.js import JetStreamManager
nc = NATS()

async def main():
    await nc.connect("nats://localhost:32645")
    # inbox = nc.new_inbox()
    # sub = await nc.subscribe('hello')
    # await nc.publish('hello', b'Hello World!')
    # await nc.publish('hello', b'Hello World!', reply=inbox)
    # await nc.publish('hello', b'With Headers', headers={'Foo': 'Bar'})
    # while True:
    #     try:
    #         msg = await sub.next_msg()
    #     except:
    #         break
    #     print('----------------------')
    #     print('Subject:', msg.subject)
    #     print('Reply  :', msg.reply)
    #     print('Data   :', msg.data)
    #     print('Headers:', msg.header)

    js = nc.jetstream()
    js_info = await js.streams_info()
    print(js_info)

    #await js.add_stream(name='command', subjects=['hello'])
    ack = await js.publish('command.add.workflow', b'Hello JS!')
    print(f'Ack: stream={ack.stream}, sequence={ack.seq}')
    await nc.close()

if __name__ == '__main__':
    asyncio.run(main())
