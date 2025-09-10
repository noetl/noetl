"""
Broker package for server-side orchestration helpers.

This package supersedes the legacy `noetl/broker.py` module and exposes
the same public API surface for server components:

- `Broker` class (lightweight local broker client)
- `execute_playbook_via_broker()` kickoff helper
- `BrokerService` and `get_broker_service()` for post-persist analysis
"""

from .core import Broker
from .execute import execute_playbook_via_broker
from .service import BrokerService, get_broker_service

__all__ = [
    "Broker",
    "execute_playbook_via_broker",
    "BrokerService",
    "get_broker_service",
]
