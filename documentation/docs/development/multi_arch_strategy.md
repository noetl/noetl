# Multi-Architecture Build Strategy

## Problem Statement

NoETL has a Rust CLI binary (`noetlctl`) that needs to work across:
- **Local development**: Mac (arm64/amd64), Linux (amd64/arm64), Windows
- **Docker containers**: Linux (amd64/arm64)
- **Kubernetes clusters**: Any node architecture

Currently:
- Single-architecture builds only
- Mac developers can't run locally without building UI assets
- Docker images locked to build host architecture

## Recommendation: YES - Implement Multi-Architecture Support

### Reasons:

1. **Development Flexibility**
   - Mac M-series developers need arm64 binaries locally
   - Intel Mac/Linux developers need amd64 binaries
   - Single Docker image works everywhere

2. **Production Flexibility**
   - Deploy to any Kubernetes cluster (amd64 or arm64 nodes)
   - Use cheaper arm64 cloud instances (AWS Graviton, GCP Tau T2A)
   - No architecture lock-in

3. **CI/CD Efficiency**
   - Build once, deploy anywhere
   - No separate build pipelines per architecture
   - Registry auto-selects correct image for host

4. **Future-Proofing**
   - arm64 adoption growing (Apple Silicon, AWS Graviton, Azure Cobalt)
   - Single image simplifies distribution

## Implementation Plan

### Phase 1: Quick Fix for Local Development

**Issue**: `python -m noetl.server` fails because UI assets missing locally

**Solution**: Run setup script
```bash
./scripts/setup_local_dev.sh
```

This script:
1. Builds UI assets from `ui-src/` → `noetl/core/ui/`
2. Builds Rust CLI for native architecture
3. Copies binary to `bin/noetl` and `noetl/bin/noetl`

**Alternative**: Disable UI for local development
```bash
export NOETL_ENABLE_UI=false
mkdir -p noetl/core/ui/assets  # Create empty directory
python -m noetl.server
```

### Phase 2: Add Buildx Support to Build Scripts

Update `docker/build-noetl-images.sh`:

```bash
# Add platform flag
--platforms linux/amd64,linux/arm64  # Build both
--platforms linux/arm64              # Build single arch
--use-buildx                         # Enable buildx
```

### Phase 3: Multi-Stage Dockerfile Optimization

The current `docker/noetl/dev/Dockerfile` already uses multi-stage builds:
1. **UI builder** (Node.js) - platform-agnostic
2. **Rust builder** - architecture-specific compilation
3. **Python runtime** - platform-agnostic

This structure is optimal for multi-arch builds.

### Phase 4: CI/CD Pipeline

Add GitHub Actions workflow for automated multi-arch builds:
- Build on push to main
- Push to ghcr.io with manifest list
- Tag with commit SHA and `latest`

## Cost-Benefit Analysis

### Costs:
- **Build time**: 2x longer for multi-arch (building twice)
- **Registry storage**: ~2x storage (two images per tag)
- **Initial setup**: ~2-4 hours to implement and test

### Benefits:
- **Developer productivity**: No architecture hassles
- **Runtime flexibility**: Deploy anywhere
- **Cost savings**: Can use cheaper arm64 instances
- **Future-proof**: Ready for arm64 adoption

**ROI**: Positive - initial investment pays off quickly

## Architecture-Specific Considerations

### Rust Cross-Compilation
Current approach uses native compilation within Docker (slow under emulation).

**Optimization**: Use `cross-rs` for faster builds:
```dockerfile
FROM rust:1.83-slim AS rust-builder
RUN cargo install cross
# Build arm64 on amd64 host (or vice versa) without emulation
RUN cross build --release --target aarch64-unknown-linux-gnu
```

### Python Packages
Most Python packages have pre-built wheels for both architectures.  
Exception: Some C extensions may need compilation - document in requirements.

### UI Assets
Platform-agnostic - build once, copy to both images.

## Immediate Action Items

1. ✅ **Fix local development** (immediate)
   ```bash
   ./scripts/setup_local_dev.sh
   ```

2. **Add buildx support** (1-2 hours)
   - Update `docker/build-noetl-images.sh`
   - Add `--platforms` flag
   - Test on Mac and Linux

3. **Update documentation** (completed)
   - Created `documentation/docs/development/multi_arch_builds.md`
   - Documents local dev setup, multi-arch builds, troubleshooting

4. **CI/CD integration** (2-4 hours)
   - Add GitHub Actions workflow
   - Configure ghcr.io push
   - Test automated builds

## Testing Strategy

1. **Local testing**:
   ```bash
   ./scripts/setup_local_dev.sh
   ./bin/noetl server start
   ```

2. **Docker single-arch**:
   ```bash
   task docker-build-noetl
   docker run noetl-local-dev:latest server start
   ```

3. **Docker multi-arch**:
   ```bash
   docker buildx build --platform linux/amd64,linux/arm64 ...
   docker buildx imagetools inspect noetl-local-dev:latest
   ```

4. **Kubernetes deployment**:
   ```bash
   task deploy-noetl
   kubectl get pods -o wide  # Verify runs on any node
   ```

## References

- [Docker Buildx Documentation](https://docs.docker.com/buildx/working-with-buildx/)
- [Rust Cross-Compilation](https://rust-lang.github.io/rustup/cross-compilation.html)
- [GitHub Actions Multi-Arch](https://docs.github.com/en/actions/publishing-packages/publishing-docker-images#publishing-images-to-github-packages)
