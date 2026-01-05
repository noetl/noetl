---
sidebar_position: 7
---

# Multi-Architecture Build Support

## Overview

NoETL supports building container images for multiple CPU architectures (amd64, arm64) using Docker Buildx. This enables:
- **Development flexibility**: Mac M-series (arm64) and Intel/AMD (amd64) developers
- **Deployment flexibility**: Deploy to any Kubernetes cluster regardless of node architecture
- **Cost optimization**: Use cheaper arm64 cloud instances where appropriate
- **CI/CD efficiency**: Build once, deploy anywhere

## Architecture Components

### Rust CLI Binary (`noetlctl`)
The Rust CLI is compiled natively within the Docker build process:
- **Dev image** (`docker/noetl/dev/Dockerfile`): Uses `rust:1.83-slim` builder
- **Standalone binary** (`noetlctl/Dockerfile`): Uses Alpine with musl static linking

### Python Application
Platform-agnostic Python code with architecture-specific Rust binary embedded.

### UI Assets
Built once with Node.js (platform-agnostic), copied into final image.

## Enabling Multi-Architecture Builds

### 1. Setup Docker Buildx

```bash
# Create buildx builder (one-time setup)
docker buildx create --name noetl-builder --use --bootstrap

# Verify builder supports multiple platforms
docker buildx inspect noetl-builder
```

### 2. Update Build Scripts

**`docker/build-noetl-images.sh`** modifications:

```bash
# Add platform arguments
PLATFORMS="linux/amd64,linux/arm64"
BUILD_PLATFORMS=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --platforms)
            PLATFORMS="$2"
            BUILD_PLATFORMS=true
            shift 2
            ;;
        # ... existing options
    esac
done

# Use buildx for multi-arch builds
if $BUILD_PLATFORMS; then
    docker buildx build \
        --platform "${PLATFORMS}" \
        ${BUILD_PROGRESS_ARGS} \
        -t "${REGISTRY}noetl-local-dev:${TAG}" \
        -f "${DOCKER_DIR}/noetl/dev/Dockerfile" \
        --push \
        "${REPO_ROOT}"
else
    # Single-arch build (existing behavior)
    docker build ${BUILD_PROGRESS_ARGS} \
        -t "${REGISTRY}noetl-local-dev:${TAG}" \
        -f "${DOCKER_DIR}/noetl/dev/Dockerfile" \
        "${REPO_ROOT}"
fi
```

### 3. Build Multi-Architecture Images

```bash
# Build for both amd64 and arm64
task docker-build-noetl --platforms linux/amd64,linux/arm64 --push --registry ghcr.io/noetl/

# Build for specific architecture
task docker-build-noetl --platforms linux/arm64 --push --registry ghcr.io/noetl/

# Local build (auto-detects native platform)
task docker-build-noetl
```

## Local Development Without Docker

### Issue: UI Assets Missing

When running `python -m noetl.server` locally (outside Docker), the UI assets directory doesn't exist because it's only built during Docker image creation.

**Solution 1: Build UI Locally**
```bash
cd ui-src
npm install
npm run build
mkdir -p ../noetl/core/ui
cp -r dist/* ../noetl/core/ui/
```

**Solution 2: Disable UI**
```bash
export NOETL_ENABLE_UI=false
python -m noetl.server --host 0.0.0.0 --port 8082
```

**Solution 3: Create Placeholder Directory**
```bash
mkdir -p noetl/core/ui/assets
# Server will detect empty directory and disable UI automatically
```

### Issue: Rust Binary Architecture Mismatch

The Rust CLI binary (`noetl`) must match your local architecture:

**Mac (arm64)**:
```bash
cd noetlctl
cargo build --release
cp target/release/noetl ../bin/noetl
```

**Mac (Intel/amd64)**:
```bash
cd noetlctl
cargo build --release --target x86_64-apple-darwin
cp target/x86_64-apple-darwin/release/noetl ../bin/noetl
```

**Linux (amd64)**:
```bash
cd noetlctl
cargo build --release --target x86_64-unknown-linux-gnu
cp target/x86_64-unknown-linux-gnu/release/noetl ../bin/noetl
```

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Build Multi-Arch Images

on:
  push:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Set up QEMU
        uses: docker/setup-qemu-action@v3
      
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
      
      - name: Login to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      
      - name: Build and push multi-arch images
        run: |
          ./docker/build-noetl-images.sh \
            --platforms linux/amd64,linux/arm64 \
            --push \
            --registry ghcr.io/${{ github.repository }}/ \
            --tag ${{ github.sha }}
```

## Testing Multi-Architecture Images

### 1. Verify Image Manifests

```bash
docker buildx imagetools inspect ghcr.io/noetl/noetl-local-dev:latest
```

Expected output shows both architectures:
```
Manifest List: yes
Manifest List Size: 2
Platforms:
  linux/amd64
  linux/arm64
```

### 2. Test on Different Architectures

```bash
# Pull and run amd64 image on any platform
docker run --platform linux/amd64 ghcr.io/noetl/noetl-local-dev:latest server start

# Pull and run arm64 image on any platform
docker run --platform linux/arm64 ghcr.io/noetl/noetl-local-dev:latest server start
```

### 3. Kubernetes Deployment

Kubernetes automatically selects the correct architecture:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: noetl-server
spec:
  template:
    spec:
      containers:
      - name: noetl
        image: ghcr.io/noetl/noetl-local-dev:latest  # Auto-selects matching arch
```

## Performance Considerations

### Build Time
- Multi-arch builds take ~2x longer (building twice)
- Use caching aggressively (`--cache-from`, `--cache-to`)
- Consider building platforms in parallel with separate jobs

### Image Size
- Manifest list adds minimal overhead (~1KB)
- Each architecture image is stored separately
- Total registry storage ≈ 2x single-arch image

### Rust Cross-Compilation
For faster builds, consider cross-compilation instead of emulation:
```dockerfile
# Use cross-rs for faster arm64 builds on amd64 hosts
FROM rust:1.83-slim AS rust-builder
RUN cargo install cross
RUN cross build --release --target aarch64-unknown-linux-gnu
```

## Troubleshooting

### "exec format error"
**Cause**: Running binary built for different architecture  
**Solution**: Rebuild for correct architecture or use multi-arch image

### QEMU emulation slow
**Cause**: Emulating foreign architecture in Docker  
**Solution**: Use native builders or cross-compilation

### Kind cluster architecture mismatch
**Cause**: Kind cluster uses host architecture  
**Solution**: Build for host architecture or use `--platform` in deployment

## Best Practices

1. **Default to native builds** for local development (faster)
2. **Use multi-arch for releases** (flexibility)
3. **Cache aggressively** to minimize rebuild time
4. **Test on both architectures** before release
5. **Document architecture requirements** in deployment guides
6. **Pin architecture** in CI/CD for reproducibility

## Related Documentation

- [Rust CLI Migration](./rust_cli_migration.md)
- [PyPI Rust Bundling](./pypi_rust_bundling.md)
- [Docker Build Process](../operations/docker_builds.md)
