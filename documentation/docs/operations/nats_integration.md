---
sidebar_position: 5
---

# NATS JetStream Integration

## Overview

NoETL uses NATS JetStream for event-driven worker coordination. The event table is the single source of truth - NATS provides lightweight notifications with event references.

## Pure Event Sourcing Architecture

Workers receive event_id references via NATS and fetch command details from the event table through the API.

**Flow:**
1. Client: POST /api/execute
2. Server: Creates execution, emits command.issued events
3. Server: Publishes to NATS: `{execution_id, event_id, command_id, step, server_url}`
4. Worker: Receives notification via pull subscription
5. Worker: GET `/api/commands/{event_id}` to fetch details
6. Worker: Executes tool
7. Worker: POST /api/events (emit command.completed)
8. Server: Evaluates next steps, emits new command.issued events

## Key Concepts

### Event Table as Single Source of Truth

- **command.issued**: Server emits when a step is ready for execution
- **command.claimed**: Worker emits to atomically claim a command
- **command.completed**: Worker emits with execution result
- **command.failed**: Worker emits on execution failure

### NATS Notifications

NATS carries lightweight references, not full command data:

```json
{
  "execution_id": 7341234567890123,
  "event_id": 7341234567890124,
  "command_id": "7341234567890123:step_name",
  "step": "step_name",
  "server_url": "http://noetl.noetl.svc.cluster.local:8082"
}
```

Workers use event_id to fetch full command details from `/api/commands/{event_id}`.

## Components

### NATS Client (noetl/core/messaging/nats_client.py)

**NATSCommandPublisher** (Server-side):
- Connects to NATS JetStream
- Creates NOETL_COMMANDS stream if not exists
- Publishes lightweight command notifications

**NATSCommandSubscriber** (Worker-side):
- Connects to NATS JetStream  
- Creates durable pull consumer per worker pool
- Subscribes to noetl.commands subject
- Acknowledges/NAKs messages based on execution success

### V2 Worker (noetl/worker/v2_worker_nats.py)

**Architecture**:
1. Subscribe to NATS noetl.commands subject
2. Receive notification: `{execution_id, event_id, command_id, step, server_url}`
3. Emit command.claimed event (atomic claim via unique constraint)
4. Fetch full command from GET `/api/commands/{event_id}`
5. Execute tool based on tool.kind
6. Emit command.completed or command.failed event

**Benefits**:
- No database polling
- Instant notification of new commands
- Horizontal scalability (multiple workers, one consumer group)
- Automatic retry via NATS (max_deliver=3)
- 30-second ack timeout

## NATS Configuration

**Stream**: NOETL_COMMANDS
- Subjects: noetl.commands
- Retention: 1 hour (3600s)
- Storage: File-based (persistent)

**Consumer**: noetl-worker-pool
- Durable: Yes
- Ack policy: Explicit
- Max deliver: 3
- Ack wait: 30 seconds

**Access**:
- K8s: nats://noetl:noetl@nats.nats.svc.cluster.local:4222
- Local (via NodePort): nats://noetl:noetl@localhost:30422

## Environment Variables

**Server**:
```bash
NATS_URL=nats://noetl:noetl@nats.nats.svc.cluster.local:4222
SERVER_API_URL=http://noetl.noetl.svc.cluster.local:8082
```

**Worker**:
```bash
NATS_URL=nats://noetl:noetl@nats.nats.svc.cluster.local:4222
SERVER_API_URL=http://noetl.noetl.svc.cluster.local:8082
```

## Monitoring

```bash
# NATS stream stats
kubectl exec -n nats nats-0 -- nats stream report

# Consumer lag
kubectl exec -n nats nats-0 -- nats consumer report NOETL_COMMANDS

# Worker subscription status
kubectl logs -n noetl -l app=noetl-worker | grep "Subscribed to"
```

## Troubleshooting

**Workers not receiving commands**:
1. Check NATS connection: kubectl logs -n nats nats-0
2. Verify stream exists: nats stream info NOETL_COMMANDS
3. Check consumer: nats consumer info NOETL_COMMANDS noetl-worker-pool
4. Verify NATS_URL environment variable

**Commands not being claimed**:
1. Check event table: SELECT * FROM noetl.event WHERE event_type = 'command.issued' ORDER BY created_at DESC LIMIT 10
2. Verify NATS published: nats stream view NOETL_COMMANDS
3. Check worker logs for errors

**Messages not acknowledged**:
1. Check ack timeout (30s default)
2. Verify worker emits events successfully
3. Check max_deliver limit (3 retries)
