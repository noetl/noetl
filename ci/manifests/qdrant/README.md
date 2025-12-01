# Qdrant Vector Database Integration

Qdrant is a vector similarity search engine with extended filtering support for NoETL embeddings and semantic search.

## Components

- **StatefulSet**: Single-node Qdrant instance with persistent storage
- **Service**: HTTP (6333) and gRPC (6334) endpoints via NodePort
- **Storage**: 5GB PVC for vector data and indexes

## Access

### HTTP API (REST)
```bash
# Via NodePort
curl http://localhost:30633

# Via port-forward
task qdrant:port-forward
curl http://localhost:6333
```

### gRPC API
```bash
# Via NodePort: localhost:30634
# Via port-forward: localhost:6334
```

## Quick Start

Deploy:
```bash
task qdrant:deploy
```

Check status:
```bash
task qdrant:status
```

Health check:
```bash
task qdrant:health
```

List collections:
```bash
task qdrant:collections
```

View logs:
```bash
task qdrant:logs
```

## Configuration

Default settings in `qdrant-config` ConfigMap:
- HTTP port: 6333
- gRPC port: 6334
- Storage path: /qdrant/storage
- On-disk payload: enabled
- Telemetry: disabled

## Resources

- Requests: 512Mi memory, 250m CPU
- Limits: 2Gi memory, 1000m CPU
- Storage: 5Gi persistent volume

## References

- [Qdrant Documentation](https://qdrant.tech/documentation/)
- [Qdrant API Reference](https://qdrant.tech/documentation/interfaces/)
- [Vector Search Guide](https://qdrant.tech/documentation/concepts/search/)
