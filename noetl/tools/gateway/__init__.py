"""
NoETL Gateway tool for communication between playbooks and the API gateway.

This tool abstracts the messaging infrastructure (NATS) from playbook authors.
Users don't need to know about NATS - they just use the gateway tool.

Actions:
- callback: Send result back to gateway (for async request-response patterns)
- wait: Pause execution and wait for external input (future enhancement)
- notify: Send a notification event (future enhancement)

For auth-related callbacks, data is sent directly.
For data-heavy callbacks, HTTP pointers can be used for data retrieval.
"""

from .executor import execute_gateway_task

__all__ = ["execute_gateway_task"]
