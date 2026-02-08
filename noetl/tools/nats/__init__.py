"""
NoETL NATS tool for JetStream, K/V Store, and Object Store operations.

This tool provides direct access to NATS features from playbooks:
- K/V Store: Key-value operations with TTL support
- Object Store: Large binary object storage
- JetStream: Message publishing and retrieval (no subscriptions/pulling)

NOTE: This tool does NOT support subscriptions or pulling, as that would
break the playbook execution model. For event-driven workflows, use
the NoETL worker's native NATS consumer.

Auth pattern:
  auth: nats_credential_name

Credential fields:
  - url: NATS server URL (e.g., nats://host:4222)
  - user: (optional) Username
  - password: (optional) Password
  - token: (optional) Auth token
"""

from .executor import execute_nats_task

__all__ = ["execute_nats_task"]
