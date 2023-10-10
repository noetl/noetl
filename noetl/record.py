import struct
import json
import base64
from loguru import logger
import uuid
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Any


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
class RecordField:
    name: str
    value: str | dict | bytes
    type: str
    length: int

    @classmethod
    def create(cls, name: str, value: Any):
        length = 0
        if isinstance(value, Iterable):
            length = len(value)
        value_type = cls.infer_type(value)
        return RecordField(
            name=name,
            value=value,
            length=length,
            type=value_type
        )

    @classmethod
    def infer_type(cls, value):
        return type(value).__name__

    def encode(self):
        encoded_value = json.dumps(self.value).encode()
        if self.name in ('metadata', 'payload'):
            encoded_value = base64.b64encode(encoded_value)
        return RecordField(
            name=self.name,
            value=encoded_value,
            length=len(encoded_value),
            type='bytes'
        )

    @classmethod
    def decode(cls, name, value):
        if not isinstance(value, bytes):
            raise ValueError("Failed to decoded")
        decoded_value = value
        if name in ('metadata', 'payload'):
            try:
                decoded_value = base64.b64decode(decoded_value)
            except (TypeError, ValueError) as e:
                raise ValueError(f"Failed to decode base64: {e}")
        try:
            decoded_value = json.loads(decoded_value.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to decode JSON: {e}")
        length = len(json.dumps(decoded_value)) if isinstance(decoded_value, dict) else len(decoded_value)
        return RecordField(
            name=name,
            value=decoded_value,
            length=length,
            type=cls.infer_type(decoded_value)
        )


    @classmethod
    def is_base64(cls, value):
        if not isinstance(value, (bytes, str)):
            return False
        if isinstance(value, str):
            value = value.encode()
        try:
            decoded_value = base64.b64decode(value)
        except (TypeError, ValueError):
            return False
        return base64.b64encode(decoded_value) == value


@dataclass
class Record:
    identifier: str
    reference: str | None
    name: RecordField
    kind: ObjectKind
    metadata: RecordField
    payload: RecordField
    timestamp: int
    offset: int | None = None

    def serialize(self):
        try:
            logger.debug(self.__str__())
            name_encoded = self.name.encode()
            metadata_encoded = self.metadata.encode()
            payload_encoded = self.payload.encode()
            record_struct = struct.pack(
                f"16s16sI{name_encoded.length}sBQI{metadata_encoded.length}sI{payload_encoded.length}s",
                self.identifier.encode(),
                self.reference.encode(),
                name_encoded.length,
                name_encoded.value,
                self.kind.value,
                self.timestamp,
                metadata_encoded.length,
                metadata_encoded.value,
                payload_encoded.length,
                payload_encoded.value
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
        name_length, name_byte, kind_byte, timestamp, metadata_length, metadata_byte, payload_length, payload_byte = unpacked_data[2:]
        return cls(
            identifier=identifier,
            reference=reference,
            name=RecordField.decode(name="name", value=name_byte),
            kind=ObjectKind(kind_byte),
            timestamp=timestamp,
            metadata=RecordField.decode(name="metadata", value=metadata_byte),
            payload=RecordField.decode(name="payload", value=payload_byte)
        )

    @classmethod
    def create(cls,
               name,
               kind,
               reference,
               metadata,
               payload
               ):
        identifier = str(uuid.uuid1())
        name_field = RecordField.create(name="name", value=name)
        metadata_field = RecordField.create(name="metadata", value=metadata)
        payload_field = RecordField.create(name="payload", value=payload)
        return cls(
            name=name_field,
            identifier=identifier,
            kind=ObjectKind.create(kind),
            reference=reference if reference else identifier,
            metadata=metadata_field,
            payload=payload_field,
            timestamp=int(datetime.now().timestamp() * 1000),
        )
