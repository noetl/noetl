---
sidebar_position: 10
---

# Rust CLI Architecture

Complete architecture documentation for NoETL's Rust-based CLI and its integration with Python components.

**Migration Status**: ✅ Complete (All 3 Phases Implemented)

## Quick Overview

NoETL uses a hybrid architecture where a Rust binary (fast, native) handles CLI operations and spawns Python processes (rich ecosystem) for server and worker functionality.

```
┌─────────────────────────────────────────────────────┐
│  User Command: noetl server start                  │
└─────────────────┬───────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────────┐
│  Rust CLI Binary (noetlctl/src/main.rs)           │
│  - Argument parsing (Clap)                         │
│  - PID management                                  │
│  - Process spawning                                │
│  - Signal handling                                 │
└─────────────────┬───────────────────────────────────┘
                  ↓
┌─────────────────────────────────────────────────────┐
│  Python Subprocess: python -m noetl.server         │
│  - FastAPI server (noetl/server/__main__.py)      │
│  - Uvicorn ASGI server                            │
│  - Database operations                            │
│  - API endpoints                                  │
└─────────────────────────────────────────────────────┘
```

## Deployment Targets

### 1. Docker Containers

**Multi-Stage Build** (`docker/noetl/dev/Dockerfile`):

```dockerfile
# Stage 1: UI Build (Node.js)
FROM node:20-alpine AS ui-builder
COPY ui-src/ ./ui-src/
RUN cd ui-src && npm ci && npm run build

# Stage 2: Rust Binary (Cargo)
FROM rust:1.83-slim AS rust-builder
COPY noetlctl/ ./
RUN cargo build --release
# Output: target/release/noetl (5.5MB)

# Stage 3: Python Environment (uv)
FROM python:3.12-slim AS builder
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY noetl/ ./noetl/
RUN uv pip install -e .

# Stage 4: Production Image
FROM python:3.12-slim AS production
COPY --from=builder /opt/noetl/.venv /opt/noetl/.venv
COPY --from=rust-builder /build/target/release/noetl /usr/local/bin/noetl
COPY --from=ui-builder /ui/ui-src/dist ./noetl/core/ui
ENV PATH="/opt/noetl/.venv/bin:$PATH"
CMD ["python", "-m", "noetl.server"]
```

**Key Points:**
- Separate build stages for isolation and caching
- Rust binary at `/usr/local/bin/noetl`
- Python environment at `/opt/noetl/.venv`
- Can override CMD with `command: [noetl, server, start]`

**Platform Support:**

The CLI supports building Docker images for different platforms via the `--platform` argument:

```bash
# Build for Linux AMD64 (default, for Kubernetes/Kind)
./bin/noetl build                           # Uses linux/amd64
./bin/noetl build --platform linux/amd64

# Build for Mac Silicon (local development)
./bin/noetl build --platform linux/arm64

# K8s commands also support platform
./bin/noetl k8s redeploy --platform linux/arm64
./bin/noetl k8s reset --platform linux/amd64
```

**Why This Matters:**
- **Mac Silicon (M1/M2/M3)**: Docker Desktop defaults to `linux/arm64` but Kubernetes Kind clusters run `linux/amd64`
- **Cross-Compilation**: Building for the wrong platform causes containers to fail silently or OOMKill in K8s
- **Local Testing**: Use `linux/arm64` for faster local Docker runs on Mac Silicon
- **Production**: Always use `linux/amd64` for Kubernetes deployments

**Default Behavior:**
- All build commands default to `linux/amd64` for Kind/K8s compatibility
- On Mac Silicon, this triggers Docker's cross-compilation (slower but correct)
- Override with `--platform` flag when needed for local-only images

### 2. Kubernetes

**Server Deployment**:
```yaml
containers:
  - name: server
    image: ghcr.io/noetl/noetl:latest
    command: [noetl]
    args: [server, start]
```

**Worker Deployment**:
```yaml
containers:
  - name: worker
    command: [noetl]
    args: [worker, start]
```

**Flow**: Pod starts → Rust CLI → Spawns `python -m noetl.worker` → Connects to NATS

### 3. Local Development

```bash
# Build and install
cd noetlctl && cargo build --release
mkdir -p ../bin
cp target/release/noetl ../bin/noetl

# Usage
./bin/noetl server start --init-db
./bin/noetl worker start
./bin/noetl build
./bin/noetl k8s deploy
```

### 4. PyPI Distribution

**Wheel Contents**:
```
noetl-2.4.0-py3-none-any.whl/
├── noetl/
│   ├── cli_wrapper.py       # Entry point wrapper
│   ├── server/__main__.py   # Server entry
│   ├── worker/__main__.py   # Worker entry
│   ├── bin/noetl           # Rust binary (5.7MB)
│   └── ... (Python modules)
└── noetl-2.4.0.dist-info/
    └── entry_points.txt    # noetl = noetl.cli_wrapper:main
```

**Installation Flow**:
```bash
pip install noetl
# Creates: ~/.local/bin/noetl → cli_wrapper.py → noetl/bin/noetl
```

**Wrapper** (`noetl/cli_wrapper.py`):
```python
def main():
    binary_path = Path(noetl.__file__).parent / 'bin' / 'noetl'
    subprocess.run([str(binary_path)] + sys.argv[1:])
```

## Implementation Details

### Server Management

**Start Server** (Rust):
```rust
async fn start_server(init_db: bool) -> Result<()> {
    // 1. Check PID file (~/.noetl/noetl_server.pid)
    if pid_file.exists() && process_exists(read_pid()?) {
        return Err("Already running");
    }
    
    // 2. Check port availability
    let port = env::var("NOETL_PORT").unwrap_or("8082");
    if TcpStream::connect(format!("0.0.0.0:{}", port)).is_ok() {
        return Err("Port in use");
    }
    
    // 3. Spawn Python subprocess
    let child = Command::new("python")
        .args(&["-m", "noetl.server", "--port", &port])
        .arg(if init_db { "--init-db" } else { "" })
        .spawn()?;
    
    // 4. Write PID file
    fs::write(pid_file, child.id().to_string())?;
    Ok(())
}
```

**Server Entry Point** (Python):
```python
# noetl/server/__main__.py
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8082)
    parser.add_argument("--init-db", action="store_true")
    args = parser.parse_args()
    
    if args.init_db:
        asyncio.run(initialize_db())
    
    from noetl.server.app import create_app
    uvicorn.run(create_app(), host=args.host, port=args.port)
```

**Stop Server** (Rust):
```rust
async fn stop_server(force: bool) -> Result<()> {
    let pid = read_pid_file()?;
    
    // Send SIGTERM for graceful shutdown
    send_signal(pid, Signal::SIGTERM)?;
    
    // Wait 10 seconds
    for _ in 0..20 {
        if !process_exists(pid)? {
            fs::remove_file(pid_file)?;
            return Ok(());
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }
    
    // Force kill if requested
    if force {
        send_signal(pid, Signal::SIGKILL)?;
    }
    Ok(())
}
```

### Worker Management

**Start Worker** (Rust):
```rust
async fn start_worker(_max_workers: Option<usize>) -> Result<()> {
    let child = Command::new("python")
        .args(&["-m", "noetl.worker"])
        .spawn()?;
    
    fs::write(pid_file, child.id().to_string())?;
    Ok(())
}
```

**Worker Entry Point** (Python):
```python
# noetl/worker/__main__.py
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--nats-url", default="nats://...")
    parser.add_argument("--server-url", default=None)
    args = parser.parse_args()
    
    from noetl.worker.v2_worker_nats import run_worker_v2_sync
    run_worker_v2_sync(nats_url=args.nats_url, server_url=args.server_url)
```

**Worker Architecture** (Python):
```python
# noetl/worker/v2_worker_nats.py
async def run_v2_worker(worker_id, nats_url, server_url):
    # 1. Connect to NATS
    subscriber = NATSCommandSubscriber(nats_url, worker_id)
    await subscriber.connect()
    
    # 2. Subscribe to commands
    async def handle_command(msg):
        command = await fetch_command(msg['queue_id'])
        result = await execute_command(command)
        await report_event(msg['execution_id'], result)
    
    await subscriber.subscribe(handle_command)
    
    # 3. Keep running
    while running:
        await asyncio.sleep(1)
```

### Build Commands

**Docker Build** (Rust):
```rust
async fn build_docker_image(no_cache: bool) -> Result<()> {
    let tag = format!("local/noetl:{}", timestamp());
    
    Command::new("docker")
        .args(&["build", "-f", "docker/noetl/dev/Dockerfile"])
        .arg("-t").arg(&tag)
        .arg(if no_cache { "--no-cache" } else { "" })
        .status()?;
    
    fs::write(".noetl_last_build_tag.txt", &tag)?;
    Ok(())
}
```

**Kubernetes Deploy** (Rust):
```rust
async fn k8s_deploy() -> Result<()> {
    let tag = fs::read_to_string(".noetl_last_build_tag.txt")?;
    
    // Load image into kind cluster
    run_command(&["kind", "load", "docker-image", &tag])?;
    
    // Update manifests
    update_manifest_image("ci/manifests/noetl/server-deployment.yaml", &tag)?;
    
    // Apply manifests
    run_command(&["kubectl", "apply", "-f", "ci/manifests/noetl/"])?;
    
    // Wait for rollout
    run_command(&["kubectl", "rollout", "status", "deployment/noetl-server"])?;
    Ok(())
}
```

## Migration History

### Phase 1: Docker & Kubernetes (Complete)
**Commit**: `58ab80f3`

- Updated Dockerfile to Rust 1.83 with multi-stage build
- Installed binary to `/usr/local/bin/noetl`
- Updated K8s manifests: `command: [noetl]`
- Created `./bin/noetl` for local development
- Added kind load to k8s deploy
- Renamed all references: noetlctl → noetl

**Result**: Rust CLI in Docker and Kubernetes

### Phase 2: PyPI Bundling (Complete)
**Commit**: `059a2d35`

- Created `noetl/cli_wrapper.py` (executes bundled binary)
- Updated `pyproject.toml`:
  - Scripts: `noetl = noetl.cli_wrapper:main`
  - Package data: `noetl/bin/noetl`
- Updated GitHub workflow to compile binary before packaging
- Added `noetl/bin/` to `.gitignore`

**Build Process**:
```bash
cargo build --release                    # Compile
cp noetlctl/target/release/noetl noetl/bin/  # Copy
uv build                                 # Package (5.7MB wheel)
uv publish                               # Upload to PyPI
```

**Result**: `pip install noetl` includes working `noetl` command

### Phase 3: Python CLI Removal (Complete)
**Commit**: `6823d3d5`

- **Deleted**: `noetl/cli/ctl.py` (1,031 lines)
- **Deleted**: `noetl/cli/__init__.py`
- **Removed**: `typer>=0.15.3` dependency
- **Created**: `noetl/server/__main__.py`
- **Created**: `noetl/worker/__main__.py`
- **Updated**: Rust CLI to call Python modules directly

**Before**: `Rust → python -m noetl.cli.ctl worker start`  
**After**: `Rust → python -m noetl.worker`

**Result**: Python CLI completely removed

## Technical Specifications

### Performance
- **Binary size**: 5.5MB (release)
- **Startup time**: ~10ms (CLI parsing)
- **Memory**: ~2MB idle
- **Python subprocess**: ~300-500ms startup, 50-100MB memory

### PID Management
- **Location**: `~/.noetl/`
- **Files**: `noetl_server.pid`, `noetl_worker_{name}.pid`
- **Format**: Plain text with PID
- **Cleanup**: Removed on shutdown, validated on startup

### Signal Handling
- **SIGTERM**: Graceful shutdown (10s timeout)
- **SIGKILL**: Force termination (after timeout or with `--force`)

### Environment Variables
**Server**:
- `NOETL_HOST` (default: 0.0.0.0)
- `NOETL_PORT` (default: 8082)
- `NOETL_ENABLE_UI` (default: false)

**Worker**:
- `NATS_URL` (NATS connection string)
- `NOETL_SERVER_URL` (API endpoint)

**Database**:
- `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`
- `POSTGRES_USER`, `POSTGRES_PASSWORD`

## Platform Support

**Current**:
- Linux x86_64 ✅
- macOS arm64 (Apple Silicon) ✅
- macOS x86_64 (Intel) ✅

**Future** (with cibuildwheel):
- Linux aarch64 (ARM)
- Windows x86_64

## Dependencies

### Rust (`noetlctl/Cargo.toml`)
```toml
clap = { version = "4.5", features = ["derive"] }
reqwest = { version = "0.12", features = ["json"] }
tokio = { version = "1", features = ["full", "process"] }
dirs = "5.0"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
anyhow = "1.0"
chrono = "0.4"
sysinfo = "0.31"    # Process management
nix = "0.29"        # Unix signals
```

### Python (Removed)
```toml
typer >= 0.15.3  ❌ Removed in Phase 3
```

## Troubleshooting

### Command not found
```bash
# Check installation
pip show noetl
python -c "import noetl; import shutil; print(shutil.which('noetl'))"

# Manual execution
python -m noetl.cli_wrapper --version
```

### Port already in use
```bash
lsof -i :8082
./bin/noetl server stop --force
NOETL_PORT=8083 ./bin/noetl server start
```

### Worker not receiving jobs
```bash
kubectl logs -n noetl deployment/noetl-worker
kubectl describe pod -n noetl -l app=noetl-worker
```

### Docker build fails
```bash
./bin/noetl build --no-cache
cd noetlctl && cargo update
```

## Performance Benchmarks

**CLI Startup**:
```bash
$ time ./bin/noetl --version
noetl 2.1.2
real    0m0.012s
```

**Docker Build Time**:
- First build: ~6 minutes
- Incremental: ~30 seconds (with cache)

**Binary Distribution**:
- Rust binary: 5.5 MB
- Python wheel: 12.3 MB (with binary)
- Docker image: 450 MB (compressed)

## References

### Internal Documentation
- [PyPI Bundling](./pypi_rust_bundling.md)
- [Docker Build](../../docker/README.md)
- [Kubernetes Deployment](../../ci/README.md)

### External Resources
- [Clap](https://docs.rs/clap/) - CLI parsing
- [Tokio](https://docs.rs/tokio/) - Async runtime
- [sysinfo](https://docs.rs/sysinfo/) - Process management

### Related Commits
- `58ab80f3` - Phase 1: Docker & K8s
- `213cd01e` - Documentation updates
- `24e8266d` - AI instructions
- `059a2d35` - Phase 2: PyPI bundling
- `6823d3d5` - Phase 3: Python CLI removal
- `b9699641` - Documentation (this file)
