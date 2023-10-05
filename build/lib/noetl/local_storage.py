import os
import struct
import json
import zlib
import base64
import asyncio
from aiofile import async_open
from loguru import logger
import uuid
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class StorageKeyError(Exception):
    pass

MAX_INDEX_RECORDS = 1000000

class ObjectKind(Enum):
    WORKFLOW = 1
    TASK = 2
    STEP = 3
    LOOP = 4
    SWITCH = 5

    @classmethod
    def create(cls, value):
        value = value.lower()
        for kind in cls:
            if kind.name.lower() == value:
                return kind
        raise ValueError(f"No match {cls.__name__} for value: {value}")


@dataclass
class Metadata:
    data_path_length: int
    data_path: str
    data_file_size: int
    data_record_count: int
    index_path_length: int
    index_path: str
    index_record_count: int
    index_first_uuid: str
    index_first_uuid_offset: int
    index_last_uuid: str
    index_last_uuid_offset: int

    def serialize(self):
        packed_data = struct.pack(
            f"I{len(self.data_path)}sQI{len(self.index_path)}sQ16sQ16s",
            self.data_path_length,
            self.data_path.encode(),
            self.data_file_size,
            self.data_record_count,
            self.index_path_length,
            self.index_path.encode(),
            self.index_record_count,
            self.index_first_uuid.encode(),
            self.index_first_uuid_offset,
            self.index_last_uuid.encode(),
            self.index_last_uuid_offset
        )

        return packed_data

    @classmethod
    def deserialize(cls, data):
        (
            data_path_length, data_path_bytes,
            data_file_size,
            data_record_count,
            index_path_length, index_path_bytes,
            index_record_count,
            index_first_uuid_bytes, index_first_uuid_offset,
            index_last_uuid_bytes, index_last_uuid_offset
        ) = struct.unpack(f"I{cls.data_path_length}sQI{cls.index_path_length}sQ16sQ16s", data)

        data_path = data_path_bytes.decode()
        index_path = index_path_bytes.decode()
        index_first_uuid = index_first_uuid_bytes.decode()
        index_last_uuid = index_last_uuid_bytes.decode()

        return cls(
            data_path_length, data_path, data_file_size, data_record_count,
            index_path_length, index_path, index_record_count,
            index_first_uuid, index_first_uuid_offset,
            index_last_uuid, index_last_uuid_offset
        )


@dataclass
class Record:
    identifier: str
    reference: str | None
    name: str
    name_length: int | None
    kind: ObjectKind
    metadata: str
    metadata_length: int | None
    payload: str
    payload_length: int | None
    timestamp: int
    offset: int | None = None

    def get_encoded(self, field_name, compress=False, base64_encode=False):
        try:
            value = getattr(self, field_name)

            if field_name in ('metadata', 'payload'):
                value = json.dumps(value).encode()
                if compress and field_name == 'payload':
                    value = zlib.compress(value)
                if base64_encode and field_name == 'payload':
                    value = base64.b64encode(value)
            else:
                value = value.encode()
            return len(value), value
        except AttributeError:
            return None, None

    def serialize(self, compress=False, base64_encode=False):
        try:
            logger.debug(self.__str__())
            name_length, name_encoded = self.get_encoded(field_name="name")
            metadata_length, metadata_encoded = self.get_encoded(
                field_name="metadata",
                compress=compress,
                base64_encode=base64_encode
            )
            payload_length, payload_encoded = self.get_encoded(
                field_name="payload",
                compress=compress,
                base64_encode=base64_encode
            )
            record_struct = struct.pack(
                f"16s16sI{name_length}sBQI{metadata_length}sI{payload_length}s",
                self.identifier.encode(),
                self.reference.encode(),
                name_length,
                name_encoded,
                self.kind.value,
                self.timestamp,
                metadata_length,
                metadata_encoded,
                payload_length,
                payload_encoded
            )
            logger.debug(record_struct)
            return record_struct
        except Exception as e:
            logger.error(f"Serialize error: {str(e)}.")

    @classmethod
    def deserialize(cls, data):
        unpacked_data = struct.unpack(
            f"16s16sI{len(data) - 68}sBQI{len(data) - 68 - 12}sI{len(data) - 68 - 12 - 4}s",
            data
        )
        identifier = unpacked_data[0].decode().strip("\x00")
        reference = unpacked_data[1].decode().strip("\x00")
        name_length, name, kind, timestamp, metadata_length, metadata, payload_length, payload = unpacked_data[2:]
        return cls(identifier, reference, name_length, name, kind, timestamp, metadata_length, metadata, payload_length,
                   payload)

    @classmethod
    def create(cls,
               name,
               kind,
               reference,
               metadata,
               payload
               ):
        identifier = str(uuid.uuid1())
        return cls(
            name=name,
            identifier=identifier,
            kind=ObjectKind.create(kind),
            reference=reference if reference else identifier,
            metadata=metadata,
            payload=payload,
            timestamp=int(datetime.now().timestamp() * 1000),
            name_length=None,
            metadata_length=None,
            payload_length=None
        )


@dataclass
class IndexEntry:
    key: str
    offset: int
    length: int

    def serialize(self):
        return struct.pack('QQQ', self.key, self.offset, self.length)

    @classmethod
    def deserialize(cls, data):
        key, offset, length = struct.unpack('QQQ', data)
        return cls(key, offset, length)


class FileHandler:
    def __init__(self, file_path, marker='rb'):
        self.file_path = file_path
        self.file_handler = None
        self.marker=marker

    async def open(self):
        try:
            self.file_handler = await async_open(self.file_path, self.marker)
        except Exception as e:
            logger.error(f"Error opening file: {e}")
            raise

    async def persist(self, data):
        try:
            if self.file_handler is None:
                await self.open()
            offset = self.file_handler.tell()
            await self.file_handler.write(data)
            await self.file_handler.flush()
            return offset
        except Exception as e:
            logger.error(f"Error writing to file: {e}")
            raise

    async def read_at_offset(self, offset, size):
        await self.file_handler.seek(offset)
        data = await self.file_handler.read(size)
        return data
    async def close(self):
        if self.file_handler is not None:
            await self.file_handler.close()
            self.file_handler = None

class Storage:
    def __init__(self, data_file_path, index_file_path):
        self.dbf_write = FileHandler(data_file_path, marker='ab')
        self.dbf_read = FileHandler(data_file_path, marker='rb')
        self.idx_write = FileHandler(index_file_path, marker='ab')
        self.idx_read = FileHandler(index_file_path, marker='rb')
        self.index = {}

    @classmethod
    async def create(cls, data_file_path, index_file_path):
        instance = cls(data_file_path, index_file_path)
        return instance

    async def open_data_file(self):
        await self.dbf_write.open()
        await self.dbf_read.open()

    async def open_index_file(self):
        await self.idx_write.open()
        await self.idx_read.open()



    async def store(self, record):
        try:
            serialized_record = record.serialize()
            hash_value = hash(record.identifier)
            offset = await self.dbf_write.persist(serialized_record)
            hash_value = hash(record.identifier) % MAX_INDEX_RECORDS

            entry = IndexEntry(hash_value, offset, len(record.serialize()))

            entry = IndexEntry(hash_value, offset, len(record.serialize()))
            entry = IndexEntry(hash_value, offset, len(record.serialize()))
            logger.info(offset)
        except StorageKeyError as e:
            logger.error(e)

    async def retrieve(self, key, decompress=False, base64_decode=False):
        pass

    async def get_parent_id(self, reference):
        pass

    async def get_record(self, identifier):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass


async def main():
    os.makedirs("noetldb", exist_ok=True)
    data_file_path = os.path.join("noetldb", "noetl.dbf")
    index_file_path = os.path.join("noetldb", "noetl.idx")

    storage = await Storage.create(data_file_path, index_file_path)

    record1 = Record.create(
        name="Workflow 1",
        kind="Workflow",
        metadata={"event_type": "workflow_started"},
        reference=None,
        payload={"field1": "value1"}
    )

    await storage.store(record1)


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(main())
