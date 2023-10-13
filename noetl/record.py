import struct
import json
import base64
from loguru import logger
import uuid
from enum import Enum
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Any
import sys

class StorageKeyError(Exception):
    pass


class RecordFieldType(Enum):
    NAME = "name"
    PAYLOAD = "payload"
    METADATA = "metadata"
    BYTES = "bytes"


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
        if self.name in (RecordFieldType.METADATA.value, RecordFieldType.PAYLOAD.value):
            encoded_value = json.dumps(self.value).encode()
            encoded_value = base64.b64encode(encoded_value)
        elif isinstance(self.value, str):
            encoded_value = self.value.encode('utf-8')
        else:
            encoded_value = self.value
        logger.debug(encoded_value)
        length = len(encoded_value)
        return RecordField(
            name=self.name,
            value=encoded_value,
            length=length,
            type=RecordFieldType.BYTES.value
        )

    @classmethod
    def decode(cls, name, value):
        if name in (RecordFieldType.METADATA.value, RecordFieldType.PAYLOAD.value):
            try:
                decoded_value = base64.b64decode(value)
                decoded_value = json.loads(decoded_value.decode())
            except (TypeError, ValueError) as e:
                raise ValueError(f"Failed to decode base64: {e}")
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                raise ValueError(f"Failed to decode JSON: {e}")
        else:
            if not isinstance(value, bytes):
                raise ValueError("Failed to decoded")
            decoded_value = value.decode('utf-8')
        length = len(json.dumps(decoded_value)) if isinstance(decoded_value, dict) else len(decoded_value)
        return RecordField(
            name=name,
            value=decoded_value,
            length=length,
            type=cls.infer_type(decoded_value)
        )

    def serialize(self):
        try:
            logger.debug(self.__str__())
            name_encoded = self.name.encode('utf-8')
            name_encoded_length = len(name_encoded)
            value_encoded = self.encode()
            field_struct = struct.pack(
                f"=II{name_encoded_length}s{value_encoded.length}s",
                name_encoded_length,
                value_encoded.length,
                name_encoded,
                value_encoded.value
            )
            return field_struct
        except Exception as e:
            logger.error(f"Serialize error: {str(e)}.")

    @classmethod
    def deserialize(cls, data):
        try:
            name_length,value_length, = struct.unpack_from('=II', data, 0)
            offset = struct.calcsize('=II')
            name_decoded, value_decoded, = struct.unpack_from(f"{name_length}s{value_length}s", data, offset)
            return cls.decode(name=name_decoded.decode('utf-8'), value=value_decoded)
        except struct.error as e:
            logger.error(f"Deserialize error: {str(e)}.")
            raise

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
    timestamp: int
    identifier: str
    reference: str | None
    name: RecordField
    kind: ObjectKind
    metadata: RecordField
    payload: RecordField
    offset: int | None = None

    def serialize(self):
        try:
            logger.debug(self.__str__())
            name_encoded = self.name.encode()
            metadata_encoded = self.metadata.encode()
            payload_encoded = self.payload.encode()
            record_struct = struct.pack(
                f"=QIIIB16s16s{name_encoded.length}s{metadata_encoded.length}s{payload_encoded.length}s",
                self.timestamp,
                name_encoded.length,
                metadata_encoded.length,
                payload_encoded.length,
                self.kind.value,
                uuid.UUID(self.identifier).bytes,
                uuid.UUID(self.reference).bytes,
                name_encoded.value,
                metadata_encoded.value,
                payload_encoded.value
            )
            return record_struct
        except Exception as e:
            logger.error(f"Serialize error: {str(e)}.")

    @classmethod
    def deserialize(cls, data):
        try:
            timestamp, name_length, metadata_length, payload_length, kind_value,  identifier, reference = \
                struct.unpack_from('=QIIIB16s16s', data, 0)
            offset = struct.calcsize('=QIIIB16s16s')
            name_encoded, metadata_encoded, payload_encoded = struct.unpack_from(
                f"{name_length}s{metadata_length}s{payload_length}s", data, offset)
            return cls(
                timestamp=timestamp,
                identifier=str(uuid.UUID(bytes=identifier)),
                reference=str(uuid.UUID(bytes=reference)),
                name=RecordField.decode(name=RecordFieldType.NAME.value, value=name_encoded),
                kind=ObjectKind(kind_value),
                metadata=RecordField.decode(name=RecordFieldType.METADATA.value, value=metadata_encoded),
                payload=RecordField.decode(name=RecordFieldType.PAYLOAD.value, value=payload_encoded)
            )
        except struct.error as e:
            logger.error(f"Deserialize error: {str(e)}.")
            raise

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
            timestamp=int(datetime.now().timestamp() * 1000),
            identifier=identifier,
            reference=reference if reference else identifier,
            name=name_field,
            kind=ObjectKind.create(kind),
            metadata=metadata_field,
            payload=payload_field,

        )
