"""
NoETL Internal API — endpoints called by the system worker pool only.

The system worker pool (per noetl/ai-meta#46) runs platform-internal
playbooks (`system/outbox_publisher`, `system/projector`, ...).  Per
the data-access-boundary rule
(``agents/rules/data-access-boundary.md`` in ai-meta), those playbooks
never touch the ``noetl.*`` schema directly — they call the server.
This module exposes the HTTP surface they need.

The endpoints are gated by a service-account bearer token only the
system pool's K8s ServiceAccount carries (env
``NOETL_INTERNAL_API_TOKEN``).  User playbooks calling these routes
get 403.

Endpoints (see ``endpoint.py``):

- ``POST /api/internal/outbox/claim`` — claim a batch of PENDING/FAILED
  outbox rows; replaces the direct-DB ``claim_outbox_batch`` call the
  Python outbox publisher uses today.
- ``POST /api/internal/outbox/mark-published`` — mark a batch published.
- ``POST /api/internal/outbox/mark-failed`` — mark a row failed with
  exponential backoff.
- ``GET /api/internal/outbox/pending-count`` — count of rows in
  PENDING/FAILED status with ``available_at <= now()``.  KEDA HTTP
  scaler trigger source.
- ``POST /api/internal/events/project`` — batch INSERT INTO
  ``noetl.event`` with ``ON CONFLICT DO NOTHING`` for idempotency.

Tracks noetl/noetl#658 → noetl/ai-meta#49.
"""

from .endpoint import router
from .schema import (
    OutboxClaimRequest,
    OutboxClaimResponse,
    OutboxRow,
    OutboxMarkPublishedRequest,
    OutboxMarkPublishedResponse,
    OutboxMarkFailedRequest,
    OutboxMarkFailedResponse,
    OutboxPendingCountResponse,
    EventsProjectRequest,
    EventsProjectResponse,
)

__all__ = [
    "router",
    "OutboxClaimRequest",
    "OutboxClaimResponse",
    "OutboxRow",
    "OutboxMarkPublishedRequest",
    "OutboxMarkPublishedResponse",
    "OutboxMarkFailedRequest",
    "OutboxMarkFailedResponse",
    "OutboxPendingCountResponse",
    "EventsProjectRequest",
    "EventsProjectResponse",
]
