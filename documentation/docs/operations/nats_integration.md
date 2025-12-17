# NoETL V2 NATS Integration

## Overview

The V2 architecture now uses NATS JetStream for event-driven worker coordination, eliminating the need for database polling.

## Architecture

```
┌──────────────┐                    ┌──────────────┐
│   Client     │                    │     NATS     │
│              │                    │  JetStream   │
└──────┬───────┘                    └───────┬──────┘
       │                                    │
       │ POST /api/v2/execute               │
       ▼                                    │
┌──────────────┐                            │
│    Server    │                            │
│   V2 API     │◄───────────────────────────┤
│              │    subscribe               │
└──────┬───────┘                            │
       │                                    │
       │ 1. Create execution                │
       │ 2. Insert command to queue         │
       │ 3. Publish to NATS ───────────────►│
       │                                    │
       │                                    │ Pull subscription
       │                                    │ (durable consumer)
       │                                    ▼
       │                            ┌──────────────┐
       │                            │   V2 Worker  │
       │                            │   (Pool)     │
       │                            └──────┬───────┘
       │                                   │
       │ GET /api/postgres/execute         │
       │ (fetch + lock command) ◄──────────┤
       │                                   │
       │                                   │ Execute tool
       │                                   │
       │ POST /api/v2/events               │
       │ (emit events) ◄───────────────────┤
       │                                   │
       │ Generate next commands            │
       │ Publish to NATS ──────────────────►
       │                                   
       ▼
```

## Components

### 1. NATS Client (`noetl/core/messaging/nats_client.py`)

**NATSCommandPublisher** (Server-side):
- Connects to NATS JetStream
- Creates `NOETL_COMMANDS` stream if not exists
- Publishes lightweight command notifications
- Message format: `{execution_id, queue_id, step, server_url}`

**NATSCommandSubscriber** (Worker-side):
- Connects to NATS JetStream  
- Creates durable pull consumer per worker
- Subscribes to `noetl.commands` subject
- Acknowledges/NAKs messages based on execution success

### 2. V2 API Updates (`noetl/server/api/v2.py`)

**Changes**:
- Added `_nats_publisher` global instance
- `get_nats_publisher()` initialization function
- `start_execution()`: Publishes to NATS after queueing commands
- `handle_event()`: Publishes to NATS when generating new commands

**Configuration**:
- `NATS_URL` env var (default: `nats://noetl:noetl@nats.nats.svc.cluster.local:4222`)
- `SERVER_API_URL` env var for worker API calls

### 3. V2 Worker with NATS (`noetl/worker/v2_worker_nats.py`)

**Architecture**:
1. Subscribe to NATS `noetl.commands` subject
2. Receive notification: `{execution_id, queue_id, step, server_url}`
3. Fetch full command from server API (atomically lock via UPDATE...RETURNING)
4. Execute tool based on `tool.kind`
5. Emit events to `POST /api/v2/events`

**Benefits**:
- No database polling
- Instant notification of new commands
- Horizontal scalability (multiple workers, one consumer group)
- Automatic retry via NATS (max_deliver=3)
- 30-second ack timeout

### 4. CLI Integration (`noetl/cli/ctl.py`)

```bash
noetlctl worker start --v2
```

Reads configuration from:
- `NATS_URL` (default: `nats://noetl:noetl@localhost:30422`)
- `SERVER_API_URL` (from settings or default: `http://localhost:8082`)

## Message Flow

### Start Execution

1. Client: `POST /api/v2/execute`
2. Server:
   - Creates execution state
   - Generates initial commands
   - Inserts to `noetl.queue` (status='queued')
   - Publishes to NATS: `{execution_id, queue_id, step, server_url}`
3. NATS: Stores message in JetStream
4. Worker: Receives notification via pull subscription

### Execute Command

1. Worker receives NATS message
2. Worker: `POST /api/postgres/execute` (UPDATE...RETURNING to lock command)
3. Worker: Executes tool (python, http, postgres, duckdb)
4. Worker: Emits events (`step.enter`, `call.done`, `step.exit`)
5. Server: Processes events, generates next commands
6. Server: Publishes next commands to NATS
7. Worker: ACKs NATS message

### Error Handling

1. Worker execution fails
2. Worker emits error event (`call.done` with error payload)
3. Worker NAKs NATS message
4. NATS redelivers up to `max_deliver=3` times
5. After max retries, message moves to dead letter

## NATS Configuration

**Stream**: `NOETL_COMMANDS`
- Subjects: `noetl.commands`
- Retention: 1 hour (3600s)
- Storage: File-based (persistent)

**Consumer**: `noetl-worker-pool` (or per-worker)
- Durable: Yes
- Ack policy: Explicit
- Max deliver: 3
- Ack wait: 30 seconds

**Access**:
- K8s: `nats://noetl:noetl@nats.nats.svc.cluster.local:4222`
- Local (via NodePort): `nats://noetl:noetl@localhost:30422`

## Deployment

### Dependencies

Add to `pyproject.toml`:
```toml
"nats-py>=2.10.0",
```

### Environment Variables

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

### Build and Deploy

```bash
# Build image with NATS support
task docker-build-noetl

# Load to kind
kind load docker-image local/noetl:$(cat .noetl_last_build_tag.txt) --name noetl

# Update deployments
kubectl set image deployment/noetl-server noetl-server=local/noetl:$(cat .noetl_last_build_tag.txt) -n noetl
kubectl set image deployment/noetl-worker worker=local/noetl:$(cat .noetl_last_build_tag.txt) -n noetl
```

### Testing

```bash
# Start execution
curl -X POST http://localhost:8082/api/v2/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/fixtures/playbooks/hello_world", "payload": {"message": "NATS Test"}}'

# Check NATS stream
kubectl exec -n nats nats-0 -- nats stream info NOETL_COMMANDS

# Check NATS consumer
kubectl exec -n nats nats-0 -- nats consumer info NOETL_COMMANDS noetl-worker-pool

# Check worker logs
kubectl logs -n noetl -l app=noetl-worker --tail=50
```

## Benefits

1. **No Polling**: Workers react instantly to new commands
2. **Scalability**: Multiple workers share durable consumer
3. **Reliability**: NATS handles message persistence and retry
4. **Decoupling**: Workers don't need direct database access for queue
5. **Observability**: NATS monitoring shows message flow
6. **Lightweight**: Notifications are small JSON messages (~100 bytes)

## Migration from V1

**V1 (Database Polling)**:
- Workers poll `noetl.queue` every N seconds
- High database load with many workers
- Latency = poll interval
- No message acknowledgment

**V2 (NATS)**:
- Workers subscribe to NATS
- Instant notification (< 10ms)
- Database only for command details
- NATS handles acknowledgment and retry

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
1. Check NATS connection: `kubectl logs -n nats nats-0`
2. Verify stream exists: `nats stream info NOETL_COMMANDS`
3. Check consumer: `nats consumer info NOETL_COMMANDS noetl-worker-pool`
4. Verify NATS_URL environment variable

**Commands stuck in queue**:
1. Check queue status: `SELECT status, COUNT(*) FROM noetl.queue GROUP BY status`
2. Verify NATS published: `nats stream view NOETL_COMMANDS`
3. Check worker logs for errors

**Messages not acknowledged**:
1. Check ack timeout (30s default)
2. Verify worker emits events successfully
3. Check max_deliver limit (3 retries)

## Next Steps

1. **Monitoring**: Add Prometheus metrics for NATS message flow
2. **Dead Letter Queue**: Handle messages that exceed max_deliver
3. **Priority Queues**: Use NATS stream subjects for priority (e.g., `noetl.commands.high`)
4. **Worker Groups**: Different consumer groups for different tool types
5. **Message Tracing**: Add correlation IDs for end-to-end observability
