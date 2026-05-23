"""Event-store port and reference adapters."""

from .ports import (
    PAYLOAD_REF_KIND_PAYLOAD_STORE,
    EventRecord,
    EventStore,
    ExpectedVersionConflict,
    canonical_event_checksum,
    payload_ref_to_dict,
)
from .postgres import PostgresEventStore

__all__ = [
    "EventRecord",
    "EventStore",
    "ExpectedVersionConflict",
    "PostgresEventStore",
    "PAYLOAD_REF_KIND_PAYLOAD_STORE",
    "canonical_event_checksum",
    "payload_ref_to_dict",
]
