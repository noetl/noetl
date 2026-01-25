# Local Development Setup - Quick Reference

## Problem

Running `python -m noetl.server` locally fails with:
```
Server failed: Directory '/Users/.../noetl/core/ui/assets' does not exist
```

**Root Cause**: UI assets are only built during Docker image creation, not available for local Python development.

## Quick Fix

```bash
# One-time setup
task setup-local-dev

# Or run script directly
./scripts/setup_local_dev.sh

# Or manually disable UI
export NOETL_ENABLE_UI=false
mkdir -p noetl/core/ui/assets
```

## What the Setup Script Does

1. **Builds UI assets** from `ui-src/` → `noetl/core/ui/`
   - Runs `npm install` and `npm run build`
   - Copies Vite build output to Python package
   
2. **Builds Rust CLI** for your native architecture
   - Compiles `noetlctl` binary with `cargo build --release`
   - Copies to `bin/noetl` and `noetl/bin/noetl`
   
3. **Sets up environment** for local development
   - All assets in place for `python -m noetl.server`
   - Binary available at `./bin/noetl` for CLI commands

## Local Development Workflow

### Start Server
```bash
# Option 1: Using Rust CLI (recommended)
./bin/noetl server start

# Option 2: Direct Python invocation
python -m noetl.server --host 0.0.0.0 --port 8082

# Option 3: With database initialization
python -m noetl.server --init-db
```

### Start Worker
```bash
# Using Rust CLI
./bin/noetl worker start

# Direct Python (deprecated)
python -m noetl.worker
```

### Rebuild After Changes

**UI changes**:
```bash
cd ui-src && npm run build
cp -r dist/* ../noetl/core/ui/
```

**Rust CLI changes**:
```bash
cd noetlctl && cargo build --release
cp target/release/noetl ../bin/noetl
```

**Python changes**:
- No rebuild needed (editable install)
- Just restart server/worker

## Multi-Architecture Support

### The Question
> Should we build binaries for all architectures to keep in the repository?

### The Answer: **NO for repo, YES for Docker**

**DON'T** commit pre-built binaries to git:
- ❌ Bloats repository size
- ❌ Causes merge conflicts
- ❌ Security concerns (binary provenance)
- ❌ CI/CD can't verify builds

**DO** build multi-arch Docker images:
- ✅ Single image works on amd64 AND arm64
- ✅ Kubernetes auto-selects correct architecture
- ✅ Developer flexibility (Mac M-series + Intel/AMD)
- ✅ Production flexibility (any cloud instance type)

### Local Development Strategy

**Mac (arm64)**:
```bash
./scripts/setup_local_dev.sh  # Builds arm64 binary automatically
```

**Mac (Intel/amd64)**:
```bash
./scripts/setup_local_dev.sh  # Builds amd64 binary automatically
```

**Linux**:
```bash
./scripts/setup_local_dev.sh  # Builds native architecture
```

**Docker/K8s Development**:
```bash
# Build multi-arch image (future enhancement)
task docker-build-noetl --platforms linux/amd64,linux/arm64

# Current: single-arch build for host platform
task docker-build-noetl
```

### Architecture Detection

The setup script automatically detects your architecture:
```bash
$ uname -m
arm64      # Mac M-series
x86_64     # Intel/AMD
aarch64    # ARM64 Linux
```

And builds the appropriate binary without manual intervention.

## Docker Multi-Architecture Strategy

### Current State
- Single-architecture builds only
- Dockerfile uses native compilation within container
- Works but locks image to build host architecture

### Recommended Enhancement
- Add Docker Buildx support for multi-arch builds
- Single manifest supporting both amd64 and arm64
- Docker/Kubernetes auto-selects correct platform

### Implementation
See [Multi-Architecture Build Strategy](./multi_arch_strategy.md) for complete details.

## Common Issues

### "UI assets not found"
**Solution**: Run `task setup-local-dev` or disable UI with `export NOETL_ENABLE_UI=false`

### "exec format error" 
**Solution**: Rebuild Rust binary for your architecture: `cd noetlctl && cargo build --release`

### "npm: command not found"
**Solution**: Install Node.js or disable UI (server works without UI)

### "cargo: command not found"
**Solution**: Install Rust from https://rustup.rs/ or use Docker for development

### Missing development tools
**Solution**: Use the OS-aware tooling playbooks to install all required tools:

```bash
# Auto-detect OS and install all dev tools
noetl run automation/development/setup_tooling.yaml --set action=install-devtools

# macOS (uses Homebrew)
noetl run automation/development/tooling_macos.yaml --set action=install-devtools

# Linux/WSL2 (uses apt-get)
noetl run automation/development/tooling_linux.yaml --set action=install-devtools
```

## Task Commands

```bash
# Setup local development
task setup-local-dev           # Build UI + Rust CLI

# Docker/K8s workflow
task bring-all                 # Complete K8s environment
task docker-build-noetl        # Build container images
task redeploy                  # Rebuild and redeploy to K8s

# Virtual environment
task venv-create               # Create .venv with dependencies
```

## Directory Structure

```
noetl/
├── bin/noetl                  # Rust CLI binary (local dev)
├── noetl/
│   ├── bin/noetl             # Bundled binary (PyPI distribution)
│   └── core/ui/              # UI assets (built from ui-src/)
│       ├── index.html
│       └── assets/
├── noetlctl/                  # Rust CLI source
│   └── target/release/noetl  # Compiled binary
├── ui-src/                    # UI source (Vite/React)
│   └── dist/                 # Build output → copied to noetl/core/ui/
└── scripts/
    └── setup_local_dev.sh    # One-command setup
```

## Related Documentation

- [Automation Playbooks](./automation_playbooks.md) - Complete playbook reference
- [Multi-Architecture Build Strategy](./multi_arch_strategy.md)
- [Multi-Architecture Builds (Implementation Guide)](./multi_arch_builds.md)
- [Rust CLI Migration](./rust_cli_migration.md)
- [PyPI Rust Bundling](./pypi_rust_bundling.md)

## OS-Aware Tooling Setup

NoETL provides playbooks that automatically detect your operating system and install required development tools:

```bash
# Detect OS and show recommended setup
noetl run automation/development/setup_tooling.yaml --set action=detect

# Install all dev tools (auto-detects macOS vs Linux/WSL2)
noetl run automation/development/setup_tooling.yaml --set action=install-devtools

# Validate installed tools
noetl run automation/development/setup_tooling.yaml --set action=validate-install
```

**Platform-specific playbooks:**
- `automation/development/tooling_macos.yaml` - macOS (uses Homebrew)
- `automation/development/tooling_linux.yaml` - Linux/WSL2 (uses apt-get)

## Quick Reference Card

| Goal | Command |
|------|---------|
| Setup for first time | `task setup-local-dev` |
| Start server locally | `./bin/noetl server start` |
| Start worker locally | `./bin/noetl worker start` |
| Disable UI | `export NOETL_ENABLE_UI=false` |
| Rebuild UI | `cd ui-src && npm run build && cp -r dist/* ../noetl/core/ui/` |
| Rebuild CLI | `cd noetlctl && cargo build --release && cp target/release/noetl ../bin/` |
| Full K8s setup | `task bring-all` |
