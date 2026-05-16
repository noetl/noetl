"""Event-store port and reference adapters."""

from .ports import EventRecord, EventStore, ExpectedVersionConflict, canonical_event_checksum
from .postgres import PostgresEventStore

__all__ = [
    "EventRecord",
    "EventStore",
    "ExpectedVersionConflict",
    "PostgresEventStore",
    "canonical_event_checksum",
]
