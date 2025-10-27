"""
Event service package - handles event persistence and workflow orchestration.

Structure:
- event_service.py: EventService class for event persistence and emission
- Orchestration modules: core, dispatcher, transitions, initial, etc.
"""

# EventService for event handling
from .event_service import (
    EventService,
    get_event_service,
    get_event_service_dependency,
)

# Orchestration functions
from .core import evaluate_execution
from .dispatcher import route_event

__all__ = [
    'EventService',
    'get_event_service', 
    'get_event_service_dependency',
    'evaluate_execution',
    'route_event'
]
