import struct
import json
import zlib
import base64
from loguru import logger
import uuid
from enum import Enum
from dataclasses import dataclass
from datetime import datetime


class StorageKeyError(Exception):
    pass

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
            logger.debug(f"length: {len(value)}, value: {value}")
            return len(value), value
        except AttributeError as e:
            logger.error(f"NoETL record attribute error: {str(e)}.")
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
