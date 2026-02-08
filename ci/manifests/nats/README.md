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
- Max file store: 1GB

### Key-Value Store
- Distributed KV operations
- TTL support
- Watch/subscribe patterns

**Session Cache Bucket:**
The Gateway uses a K/V bucket named `sessions` to cache authenticated sessions:
- Automatic creation on first use
- Default TTL: 5 minutes (configurable via `NATS_SESSION_CACHE_TTL_SECS`)
- Reduces playbook calls for session validation

### Accounts
- **$SYS** account (sys/sys) - System monitoring
- **NOETL** account (noetl/noetl) - JetStream enabled for K/V and streams

**Note:** JetStream K/V access requires the account-based configuration. The `noetl` user has full JetStream permissions within the NOETL account.

## Access

### Client Connection
```bash
# Via NodePort
nats -s nats://noetl:noetl@localhost:30422

# Via port-forward
noetl run automation/infrastructure/nats.yaml --set action=port-forward
nats -s nats://noetl:noetl@localhost:4222
```

### Monitoring Dashboard
```bash
# Via NodePort
curl http://localhost:30822/varz

# Via port-forward
noetl run automation/infrastructure/nats.yaml --set action=port-forward
open http://localhost:8222
```

## Quick Start

Deploy:
```bash
noetl run automation/infrastructure/nats.yaml --set action=deploy
```

Check status:
```bash
noetl run automation/infrastructure/nats.yaml --set action=status
```

Health check:
```bash
noetl run automation/infrastructure/nats.yaml --set action=health
```

View streams:
```bash
noetl run automation/infrastructure/nats.yaml --set action=streams
```

View logs:
```bash
noetl run automation/infrastructure/nats.yaml --set action=logs
```

## Configuration

Default settings in `nats-config` ConfigMap:
- Client port: 4222
- HTTP monitoring: 8222
- JetStream storage: /data/jetstream
- JetStream max memory: 1GB
- JetStream max file: 5GB

**Accounts Configuration:**
```conf
accounts {
  $SYS {
    users: [ { user: sys, password: sys } ]
  }
  NOETL {
    jetstream: enabled
    users: [ { user: noetl, password: noetl } ]
  }
}
```

**Important:** The account-based configuration is required for JetStream K/V operations. Simple `authorization { user/password }` blocks don't grant JetStream permissions.

## Resources

- Requests: 200Mi memory, 200m CPU
- Limits: 200Mi memory,  200m CPU
- Storage: 1Gi persistent volume

## References

- [NATS Documentation](https://docs.nats.io/)
- [JetStream Guide](https://docs.nats.io/nats-concepts/jetstream)
- [Key-Value Store](https://docs.nats.io/nats-concepts/jetstream/key-value-store)
