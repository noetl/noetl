"""
NoETL Broker API Package - Event handling and workflow orchestration.

This package handles:
1. Event emission from workers (POST /api/events for worker compatibility)
2. Event storage in event table (pure event sourcing)
3. Triggering orchestrator to analyze events and publish next tasks to queue

Architecture:
- Workers execute tasks → Report results via POST /api/events
- Broker stores events → Triggers orchestrator
- Orchestrator analyzes event state → Publishes actionable tasks to queue
- Workers pick up tasks → Execute → Report back to broker (cycle repeats)

Pattern: Event sourcing with state reconstruction from event log.
Previously named 'event' package, renamed to 'broker' to reflect its role
as the central event broker coordinating between workers and orchestrator.
"""

from .endpoint import router
from .schema import (
    EventType,
    EventStatus,
    EventEmitRequest,
    EventEmitResponse,
    EventQuery,
    EventResponse,
    EventListResponse
)
from .service import EventService


__all__ = [
    "router",
    "EventType",
    "EventStatus",
    "EventEmitRequest",
    "EventEmitResponse",
    "EventQuery",
    "EventResponse",
    "EventListResponse",
    "EventService"
]
