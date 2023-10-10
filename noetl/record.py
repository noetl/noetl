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
        if self.name in ('metadata', 'payload'):
            encoded_value = json.dumps(self.value).encode()
            encoded_value = base64.b64encode(encoded_value)
        elif isinstance(self.value, str):
            encoded_value = self.value.encode('utf-8')
        else:
            encoded_value = self.value
        logger.debug(encoded_value)
        return RecordField(
            name=self.name,
            value=encoded_value,
            length=len(encoded_value),
            type='bytes'
        )

    @classmethod
    def decode(cls, name, value):
        if name in ('metadata', 'payload'):
            try:
                logger.debug(value)
                decoded_value = base64.b64decode(value)
                logger.info(decoded_value)
                decoded_value = json.loads(decoded_value.decode())
                logger.info(decoded_value)
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
                uuid.UUID(self.identifier).bytes,
                uuid.UUID(self.reference).bytes,
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

    # @classmethod
    # def deserialize(cls, data):
    #     unpacked_data = struct.unpack(
    #         f"16s16sI{len(data) - 68}sBQI{len(data) - 68 - 12}sI{len(data) - 68 - 12 - 4}s",
    #         data
    #     )
    #     identifier = unpacked_data[0].decode().strip("\x00")
    #     reference = unpacked_data[1].decode().strip("\x00")
    #     name_length, name_byte, kind_byte, timestamp, metadata_length, metadata_byte, payload_length, payload_byte = unpacked_data[2:]
    #     return cls(
    #         identifier=identifier,
    #         reference=reference,
    #         name=RecordField.decode(name="name", value=name_byte),
    #         kind=ObjectKind(kind_byte),
    #         timestamp=timestamp,
    #         metadata=RecordField.decode(name="metadata", value=metadata_byte),
    #         payload=RecordField.decode(name="payload", value=payload_byte)
    #     )

    @classmethod
    def deserialize(cls, data):
        try:
            identifier, reference, name_length = struct.unpack('16s16sI', data[:36])
            identifier_decoded =  str(uuid.UUID(bytes=struct.unpack('16s', identifier)[0]))
            reference_decoded = str(uuid.UUID(bytes=struct.unpack('16s', reference)[0]))
            logger.debug(f"{identifier_decoded} , {reference_decoded} , {name_length}")
            name_end = 36 + name_length
            name_decoded = RecordField.decode(name="name",value=data[36:name_end])
            logger.debug(name_decoded)

            logger.debug(f"name_end: {name_end}, data[name_end:name_end + 12]: {data[name_end:name_end + 12]}")

            bq_slice = data[name_end:name_end + 9]
            logger.info(f"{bq_slice} {len(bq_slice)}")
            kind_value, timestamp = struct.unpack('=BQ', bq_slice)
            logger.info(f"{kind_value}, {timestamp}")

            metadata_start = name_end + 13
            metadata_length = struct.unpack('I', data[name_end + 9:metadata_start])[0]
            logger.debug(metadata_length)
            metadata_end = metadata_start + metadata_length
            logger.debug(metadata_end)
            metadata_value = RecordField.decode(name="metadata",value=data[metadata_start:metadata_end])
            logger.info(metadata_value)


            payload_length = struct.unpack('I', data[metadata_end:metadata_end + 4])[0]
            payload_value = data[metadata_end + 4:metadata_end + 4 + payload_length]
            return cls(
                identifier=identifier.decode(),
                reference=reference.decode(),
                name=RecordField(length=name_length, value=name_value),
                kind=ObjectKind(kind_value),
                metadata=RecordField(length=metadata_length, value=metadata_value),
                payload=RecordField(length=payload_length, value=payload_value),
                timestamp=timestamp
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
            name=name_field,
            identifier=identifier,
            kind=ObjectKind.create(kind),
            reference=reference if reference else identifier,
            metadata=metadata_field,
            payload=payload_field,
            timestamp=int(datetime.now().timestamp() * 1000),
        )
