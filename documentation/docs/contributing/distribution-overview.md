---
sidebar_position: 1
---

# Distribution Overview

NoETL CLI is distributed through multiple channels to support different platforms and package managers.

## Package Naming

The NoETL CLI uses different names across distribution channels:

| Channel | Package Name | Binary Name | Directory |
|---------|-------------|-------------|-----------|
| **Crates.io** | `noetl` | `noetl` | `crates/noetlctl` |
| **PyPI** | `noetlctl` | `noetl` | `crates/noetlctl` |
| **Homebrew** | `noetl` | `noetl` | `crates/noetlctl` |
| **APT** | `noetl` | `noetl` | `crates/noetlctl` |

**Rationale**:
- **Crates.io**: `noetl` for clean cargo install command
- **PyPI**: `noetlctl` to avoid conflicts, descriptive "noetl control"
- **Homebrew/APT**: `noetl` for simplicity
- **Directory**: `noetlctl` for descriptive naming in repository

All packages install the same Rust binary named `noetl`.

## Distribution Channels

### 1. Crates.io (Rust)

**Package**: https://crates.io/crates/noetl  
**Install**: `cargo install noetl`  
**Platform**: Cross-platform (requires Rust toolchain)

**Pros**:
- Native Rust ecosystem
- Latest updates available quickly
- Source-based builds with optimization options

**Release Process**: See [Crates.io Releases](./crates-releases.md)

### 2. PyPI (Python)

**Package**: https://pypi.org/project/noetlctl/  
**Install**: `pip install noetlctl`  
**Platform**: Pre-built wheels for macOS, Linux, Windows

**Pros**:
- No Rust toolchain required
- Fast installation (pre-compiled binaries)
- Works in Python virtual environments

**Technical**: Built with [maturin](https://www.maturin.rs/) using `bin` bindings

**Release Process**: See [Maturin Release](../release/noetl-cli-maturin.md)

### 3. Homebrew (macOS)

**Tap**: https://github.com/noetl/homebrew-tap  
**Install**: `brew install noetl`  
**Platform**: macOS (Apple Silicon & Intel)

**Pros**:
- Native macOS package management
- Automatic updates with `brew upgrade`
- No Rust toolchain required for users

**Release Process**: See [Homebrew Releases](./homebrew-releases.md)

### 4. APT (Ubuntu/Debian)

**Repository**: https://noetl.github.io/apt  
**Install**: `sudo apt-get install noetl`  
**Platform**: Ubuntu/Debian (amd64, arm64)

**Pros**:
- Native Linux package management
- System-wide installation
- Integration with apt-get workflow

**Build**: Docker-based for cross-platform building from macOS

**Release Process**: See [APT Releases](./apt-releases.md)

## Installation Matrix

| Platform | Recommended Method | Alternative |
|----------|-------------------|-------------|
| **macOS** | Homebrew | Crates.io, PyPI |
| **Ubuntu/Debian** | APT | Crates.io, PyPI |
| **Other Linux** | Crates.io | PyPI |
| **Windows** | PyPI | Crates.io |
| **CI/CD** | Crates.io | PyPI, Docker |

## Version Synchronization

All distribution channels should maintain version parity:

**Workspace Version** (root `Cargo.toml`):
```toml
[workspace.package]
version = "2.5.3"
```

**Package Versions**:
- Crates.io: `noetl` v2.5.3
- PyPI: `noetlctl` v2.5.3
- Homebrew: Formula URL with `v2.5.3` tag
- APT: Package version `2.5.3-1`

## Release Workflow

For a new version (e.g., 2.5.5):

1. **Update version** in `Cargo.toml` workspace
2. **Create git tag**: `v2.5.5`
3. **Push tag**: `git push origin v2.5.5`
4. **Publish to Crates.io**: `./scripts/publish_crate.sh`
5. **Build Debian package**: `./docker/release/build-deb-docker.sh 2.5.5`
6. **Publish APT repo**: `./scripts/publish_apt.sh 2.5.5`
7. **Update Homebrew**: `./scripts/homebrew_publish.sh 2.5.5`
8. **Publish to PyPI**: `cd crates/noetlctl && maturin publish`

## Docker-Based Building

For developers on macOS or Windows who need to build Linux packages:

### Debian Package
```bash
./docker/release/build-deb-docker.sh 2.5.4
```

Output: `build/deb/noetl_2.5.5-1_amd64.deb`

### Test Installation
```bash
docker run --rm -v $(pwd)/build/deb:/packages ubuntu:22.04 bash -c '
  apt-get update && 
  dpkg -i /packages/noetl_2.5.5-1_amd64.deb && 
  noetl --version'
```

## Automation

### GitHub Actions

Create workflows for automated publishing:

- `.github/workflows/publish-crates.yml` - Publish to crates.io on tag push
- `.github/workflows/build-deb.yml` - Build and publish Debian packages
- `.github/workflows/update-homebrew.yml` - Update Homebrew tap

### Manual Scripts

Located in `scripts/`:
- `publish_crate.sh` - Crates.io publishing with validation
- `build_deb.sh` - Native Debian package building
- `publish_apt.sh` - APT repository generation
- `homebrew_publish.sh` - Homebrew formula SHA256 update

Located in `docker/release/`:
- `build-deb-docker.sh` - Docker-based Debian building
- `Dockerfile.deb` - Ubuntu build environment

## Troubleshooting

### Package Name Confusion

**Q**: Why is the crate named `noetl` but directory is `noetlctl`?  
**A**: For clean cargo install (`cargo install noetl`) while keeping descriptive directory naming.

**Q**: Why is PyPI package named `noetlctl`?  
**A**: To avoid namespace conflicts and be more descriptive ("noetl control").

### Version Mismatches

Ensure all packages use the same version from workspace:

```bash
# Check workspace version
grep 'version =' Cargo.toml

# Verify crate version
grep 'version' crates/noetlctl/Cargo.toml

# Verify PyPI version
grep 'version' crates/noetlctl/pyproject.toml
```

### Build Failures

**Docker build fails on macOS**:
- Ensure Docker Desktop is running
- Check available disk space
- Try: `docker system prune -a`

**Rust compilation errors**:
- Update Rust: `rustup update`
- Clean build: `cargo clean && cargo build`

## Support Matrix

| Platform | Architecture | Package Manager | Status |
|----------|--------------|----------------|--------|
| macOS | Apple Silicon | Homebrew, Cargo, PyPI | ✅ Supported |
| macOS | Intel | Homebrew, Cargo, PyPI | ✅ Supported |
| Ubuntu 24.04 | amd64 | APT, Cargo, PyPI | ✅ Supported |
| Ubuntu 22.04 | amd64 | APT, Cargo, PyPI | ✅ Supported |
| Ubuntu 20.04 | amd64 | APT, Cargo, PyPI | ✅ Supported |
| Ubuntu | arm64 | APT, Cargo, PyPI | 🚧 Coming Soon |
| Debian | amd64 | APT, Cargo, PyPI | ✅ Supported |
| Other Linux | amd64 | Cargo, PyPI | ✅ Supported |
| Windows | x86_64 | PyPI, Cargo | ⚠️ Limited Testing |

## Documentation

- [Cargo Installation](../installation/cargo.md)
- [Homebrew Installation](../installation/homebrew.md)
- [APT Installation](../installation/apt.md)
- [Crates.io Releases](./crates-releases.md)
- [Homebrew Releases](./homebrew-releases.md)
- [APT Releases](./apt-releases.md)
- [Maturin/PyPI Release](../release/noetl-cli-maturin.md)
