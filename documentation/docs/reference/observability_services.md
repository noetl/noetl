# NoETL Observability Services

Complete guide for ClickHouse, Qdrant, and NATS integration in NoETL infrastructure.

## Overview

NoETL includes three observability and data services:

1. **ClickHouse**: OLAP database for logs, metrics, and traces
2. **Qdrant**: Vector database for embeddings and semantic search
3. **NATS JetStream**: Messaging and key-value store

## Quick Start

### Activate All Services
```bash
noetl run automation/infrastructure/observability.yaml --set action=deploy
```

### Deactivate All Services
```bash
noetl run automation/infrastructure/observability.yaml --set action=remove
```

### Individual Service Control
```bash
# Deploy individual services
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy
noetl run automation/infrastructure/qdrant.yaml --set action=deploy
noetl run automation/infrastructure/nats.yaml --set action=deploy

# Remove individual services
noetl run automation/infrastructure/clickhouse.yaml --set action=remove
noetl run automation/infrastructure/qdrant.yaml --set action=remove
noetl run automation/infrastructure/nats.yaml --set action=remove
```

## ClickHouse

### Purpose
Columnar analytical database for high-performance analytics on logs, metrics, and traces.

### Access Points
- HTTP: `localhost:30123` (NodePort)
- Native: `localhost:30900` (NodePort)
- MCP Server: `localhost:8124`

### Key Features
- OpenTelemetry-compatible schema
- 4 main tables: logs, metrics, traces, noetl_events
- Materialized views for analytics
- ZSTD compression, bloom filter indexes
- TTL policies (30-90 days)

### Common Operations
```bash
noetl run automation/infrastructure/clickhouse.yaml --set action=status    # Show status
noetl run automation/infrastructure/clickhouse.yaml --set action=connect   # Connect to CLI
noetl run automation/infrastructure/clickhouse.yaml --set action=health    # Health check
noetl run automation/infrastructure/clickhouse.yaml --set action=logs      # View logs
```

### Documentation
See `docs/clickhouse_observability.md` for detailed guide.

## Qdrant

### Purpose
Vector similarity search engine for embeddings, semantic search, and RAG applications.

### Access Points
- HTTP API: `localhost:30633` (NodePort)
- gRPC API: `localhost:30634` (NodePort)

### Key Features
- Vector similarity search
- Extended filtering support
- On-disk payload storage
- Collection-based organization
- 5GB persistent storage

### Common Operations
```bash
noetl run automation/infrastructure/qdrant.yaml --set action=status       # Show status
noetl run automation/infrastructure/qdrant.yaml --set action=health       # Health check
noetl run automation/infrastructure/qdrant.yaml --set action=collections  # List collections
noetl run automation/infrastructure/qdrant.yaml --set action=logs         # View logs
noetl run automation/infrastructure/qdrant.yaml --set action=test         # Run tests
```

### API Examples

#### Create Collection
```bash
curl -X PUT "http://localhost:30633/collections/my_collection" \
  -H "Content-Type: application/json" \
  -d '{
    "vectors": {
      "size": 384,
      "distance": "Cosine"
    }
  }'
```

#### Insert Vectors
```bash
curl -X PUT "http://localhost:30633/collections/my_collection/points" \
  -H "Content-Type: application/json" \
  -d '{
    "points": [
      {
        "id": 1,
        "vector": [0.1, 0.2, ...],
        "payload": {"text": "example"}
      }
    ]
  }'
```

#### Search
```bash
curl -X POST "http://localhost:30633/collections/my_collection/points/search" \
  -H "Content-Type: application/json" \
  -d '{
    "vector": [0.1, 0.2, ...],
    "limit": 10
  }'
```

## NATS JetStream

### Purpose
Messaging system with streaming and key-value store for event-driven workflows.

### Access Points
- Client: `localhost:30422` (NodePort)
- Monitoring: `localhost:30822` (NodePort)

### Key Features
- JetStream persistence (5GB)
- Key-value store
- Stream-based messaging
- Consumer groups
- Message replay
- Credentials: noetl/noetl

### Common Operations
```bash
noetl run automation/infrastructure/nats.yaml --set action=status      # Show status
noetl run automation/infrastructure/nats.yaml --set action=health      # Health check
noetl run automation/infrastructure/nats.yaml --set action=streams     # List streams
noetl run automation/infrastructure/nats.yaml --set action=monitoring  # Show monitoring
noetl run automation/infrastructure/nats.yaml --set action=logs        # View logs
noetl run automation/infrastructure/nats.yaml --set action=test        # Run tests
```

### CLI Examples

#### Publish Message
```bash
nats -s nats://noetl:noetl@localhost:30422 pub subject.name "message"
```

#### Subscribe to Subject
```bash
nats -s nats://noetl:noetl@localhost:30422 sub subject.name
```

#### Create Stream
```bash
nats -s nats://noetl:noetl@localhost:30422 stream add \
  --subjects="events.*" \
  --storage=file \
  --retention=limits \
  --max-age=24h
```

#### KV Operations
```bash
# Create KV bucket
nats -s nats://noetl:noetl@localhost:30422 kv add config

# Put value
nats -s nats://noetl:noetl@localhost:30422 kv put config key value

# Get value
nats -s nats://noetl:noetl@localhost:30422 kv get config key
```

## Unified Operations

### Status Check
```bash
noetl run automation/infrastructure/observability.yaml --set action=status
```

### Health Check
```bash
noetl run automation/infrastructure/observability.yaml --set action=health
```

### Restart All
```bash
noetl run automation/infrastructure/observability.yaml --set action=restart
```

## Integration with NoETL

### Bootstrap Integration
All services automatically deploy with:
```bash
noetl run automation/setup/bootstrap.yaml
```

### Service Endpoints in Bootstrap Output
```
NoETL started!
  UI: http://localhost:8083
  Grafana: kubectl port-forward -n vmstack svc/vmstack-grafana 3000:80
  ClickHouse HTTP: localhost:30123 (NodePort)
  ClickHouse Native: localhost:30900 (NodePort)
  Qdrant HTTP: localhost:30633 (NodePort)
  Qdrant gRPC: localhost:30634 (NodePort)
  NATS Client: localhost:30422 (NodePort)
  NATS Monitoring: localhost:30822 (NodePort)
```

## Resource Requirements

### ClickHouse
- Memory: 512Mi-2Gi
- CPU: 500m-2000m
- Storage: 5Gi data + 1Gi logs

### Qdrant
- Memory: 512Mi-2Gi
- CPU: 250m-1000m
- Storage: 5Gi

### NATS
- Memory: 512Mi-2Gi
- CPU: 250m-1000m
- Storage: 5Gi

**Total**: ~3.5-6Gi memory, ~2-4 CPU cores, ~16Gi storage

## Troubleshooting

### Services Not Starting
```bash
# Check pod status
kubectl get pods -n clickhouse
kubectl get pods -n qdrant
kubectl get pods -n nats

# Check logs
kubectl logs -n clickhouse deployment/clickhouse -f
kubectl logs -n qdrant deployment/qdrant -f
kubectl logs -n nats deployment/nats -f

# Describe pods for events
kubectl describe pod -n clickhouse
kubectl describe pod -n qdrant
kubectl describe pod -n nats
```

### Connection Issues
```bash
# Test from within cluster
kubectl run -it --rm test --image=busybox --restart=Never -- \
  wget -qO- http://clickhouse.clickhouse.svc.cluster.local:8123

kubectl run -it --rm test --image=busybox --restart=Never -- \
  wget -qO- http://qdrant.qdrant.svc.cluster.local:6333

kubectl run -it --rm test --image=busybox --restart=Never -- \
  nc -zv nats.nats.svc.cluster.local 4222
```

### Storage Issues
```bash
# Check PVCs
kubectl get pvc -n clickhouse
kubectl get pvc -n qdrant
kubectl get pvc -n nats

# Check storage usage
kubectl exec -n clickhouse <pod> -- df -h /qdrant/storage
kubectl exec -n qdrant <pod> -- df -h /qdrant/storage
kubectl exec -n nats <pod> -- df -h /data
```

## Production Considerations

### ClickHouse
- Use multi-node clusters for replication
- Configure S3 backups
- Tune partitioning and TTL policies
- Monitor query performance

### Qdrant
- Scale horizontally with sharding
- Configure snapshots for backups
- Optimize index parameters
- Monitor memory usage

### NATS
- Use clustering for high availability
- Configure stream replication
- Set appropriate retention policies
- Monitor JetStream usage

## References

- [ClickHouse Documentation](https://clickhouse.com/docs)
- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [NATS Documentation](https://docs.nats.io/)
- [NoETL ClickHouse Guide](clickhouse_observability.md)
