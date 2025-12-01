# NATS JetStream Integration

NATS with JetStream provides messaging, streaming, and key-value store capabilities for NoETL event-driven workflows.

## Components

- **StatefulSet**: Single-node NATS server with JetStream enabled
- **Service**: Client (4222) and Monitoring (8222) endpoints via NodePort
- **Storage**: 5GB PVC for JetStream persistence

## Features

### JetStream
- Stream-based messaging
- Message persistence and replay
- Consumer groups
- Max memory: 1GB
- Max file store: 5GB

### Key-Value Store
- Distributed KV operations
- TTL support
- Watch/subscribe patterns

### Accounts
- System account (sys/sys)
- Default account (noetl/noetl) with JetStream enabled

## Access

### Client Connection
```bash
# Via NodePort
nats -s nats://noetl:noetl@localhost:30422

# Via port-forward
task nats:port-forward
nats -s nats://noetl:noetl@localhost:4222
```

### Monitoring Dashboard
```bash
# Via NodePort
curl http://localhost:30822/varz

# Via port-forward
task nats:port-forward
open http://localhost:8222
```

## Quick Start

Deploy:
```bash
task nats:deploy
```

Check status:
```bash
task nats:status
```

Health check:
```bash
task nats:health
```

View streams:
```bash
task nats:streams
```

View logs:
```bash
task nats:logs
```

## Configuration

Default settings in `nats-config` ConfigMap:
- Client port: 4222
- HTTP monitoring: 8222
- JetStream storage: /data/jetstream
- Default user: noetl/noetl

## Resources

- Requests: 512Mi memory, 250m CPU
- Limits: 2Gi memory, 1000m CPU
- Storage: 5Gi persistent volume

## References

- [NATS Documentation](https://docs.nats.io/)
- [JetStream Guide](https://docs.nats.io/nats-concepts/jetstream)
- [Key-Value Store](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
