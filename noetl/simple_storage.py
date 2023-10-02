import os
import struct
import json
import zlib
import base64
import asyncio
from aiofile import async_open
from loguru import logger


class StorageKeyError(Exception):
    pass


class Storage:
    def __init__(self, db_file_path, index_file_path):
        self.db_file_path = db_file_path
        self.index_file_path = index_file_path
        self.index = {}

    @classmethod
    async def create(cls, db_file_path, index_file_path):
        instance = cls(db_file_path, index_file_path)
        await instance.load_index()
        return instance

    async def load_index(self):
        if os.path.exists(self.index_file_path):
            async with async_open(self.index_file_path, 'rb') as afp:
                key_length_data = await afp.read(4)
                while key_length_data:
                    key_length = struct.unpack("I", key_length_data)[0]
                    key_data = await afp.read(key_length)
                    offset_data = await afp.read(8)
                    offset = struct.unpack("Q", offset_data)[0]
                    key = bytes(key_data)
                    self.index[key] = offset
                    key_length_data = await afp.read(4)

    async def store(self, key, data, compress=False, base64_encode=False, update=False):
        try:
            if key in self.index and not update:
                logger.warning(f"Key '{key}' already exists.")
                return
                # raise KeyError(f"Key '{key}' already exists.")
            json_data = json.dumps(data).encode()
            if compress:
                json_data = zlib.compress(json_data)
            if base64_encode:
                json_data = base64.b64encode(json_data)
            key_length = len(key)
            value_length = len(json_data)
            record = (
                    struct.pack("I", key_length) +
                    key +
                    struct.pack("I", value_length) +
                    json_data
            )
            offset = await self.write_to_file(record)
            self.index[key] = offset
            await self.update_index()
        except StorageKeyError as e:
            logger.error(e)

    async def retrieve(self, key, decompress=False, base64_decode=False):
        if key in self.index:
            offset = self.index[key]
            key_length_data = await self.read_from_file(offset, length=4)
            key_length = struct.unpack("I", key_length_data)[0]
            # key_data = await self.read_from_file(offset + 4, length=key_length)
            value_length_offset = offset + 4 + key_length
            value_length_data = await self.read_from_file(value_length_offset, length=4)
            value_length = struct.unpack("I", value_length_data)[0]
            value_data_offset = value_length_offset + 4
            value_data = await self.read_from_file(value_data_offset, length=value_length)
            if base64_decode:
                value_data = base64.b64decode(value_data)
            if decompress:
                value_data = zlib.decompress(value_data)
            json_data = value_data.decode()
            return json.loads(json_data)
        return None

    async def update(self, key, data, compress=False, base64_encode=False):
        try:
            if key not in self.index:
                raise StorageKeyError(f"Key '{key}' does not exist.")
            await self.store(key, data, compress, base64_encode, update=True)
        except StorageKeyError as e:
            logger.error(e)

    async def delete(self, key):
        if key in self.index:
            del self.index[key]
            await self.update_index()
            return True
        return False

    async def update_index(self):
        async with async_open(self.index_file_path, 'wb') as index_file:
            for key, offset in self.index.items():
                key_length = len(key)
                await index_file.write(struct.pack("I", key_length))
                await index_file.write(key)
                await index_file.write(struct.pack("Q", offset))

    async def write_to_file(self, data):
        try:
            async with async_open(self.db_file_path, 'ab') as afp:
                offset = afp.tell()
                await afp.write(data)
                await afp.flush()
                return offset
        except Exception as e:
            logger.error(f"Error writing to file: {e}")
            raise

    async def read_from_file(self, offset=0, length=4):
        async with async_open(self.db_file_path, 'rb') as afp:
            afp.seek(offset)
            return await afp.read(length)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass


async def main():
    os.makedirs("noetldb", exist_ok=True)
    db_file_path = os.path.join("noetldb","noetl.dbf")
    index_file_path = os.path.join("noetldb","noetl.idx")

    storage = await Storage.create(db_file_path, index_file_path)
    logger.info(storage.index)

    data = {"name": "Alex", "age": 30, "city": "Nazareth"}

    await storage.store(b"key1", data)

    retrieved_data = await storage.retrieve(b"key1")
    print(retrieved_data)

    data = {"name": "Alex", "age": 33, "city": "Nazareth"}

    await storage.store(b"key2", data)

    retrieved_data = await storage.retrieve(b"key2")
    print(retrieved_data)

    retrieved_data = await storage.retrieve(b"key1")
    print(retrieved_data)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
