"""
DEPRECATION NOTICE: Queue API Endpoints

These endpoints are being deprecated in favor of the event-driven v2 architecture.

Workers should:
1. Poll queue table directly (via database)
2. Execute commands
3. Emit events to POST /api/v2/events

Server is the ONLY component that writes to queue table via the event processing engine.

The following endpoints will be removed in a future version:
- POST /queue/{queue_id}/complete
- POST /queue/{queue_id}/fail
- POST /queue/{queue_id}/heartbeat
- PATCH /queue/{queue_id}/extend-lease

Workers should NOT call these endpoints. Use event emission instead.
"""

# This file serves as documentation for the deprecation.
# The actual endpoint implementations remain in endpoint.py for backward compatibility
# but should not be used for new v2 workflows.
