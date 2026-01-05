---
sidebar_position: 6
---

# PyPI Rust Binary Bundling

This document describes how the NoETL Rust CLI (`noetl`) is bundled with the Python package for PyPI distribution.

## Overview

NoETL uses `setuptools-rust` to compile and bundle the Rust binary during the Python package build process. When users install NoETL via `pip install noetl`, they automatically get both the Python library and the `noetl` command-line tool.

## Configuration

### Build System (`pyproject.toml`)

```toml
[build-system]
requires = ["setuptools>=45", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.package-data]
"noetl" = ["core/ui/**/*", "database/ddl/**/*", "bin/noetl"]

[project.scripts]
noetl = "noetl.cli_wrapper:main"
```

**Key Components:**
- Standard setuptools build (no setuptools-rust needed)
- Binary included as package data in `noetl/bin/noetl`
- Python wrapper script (`noetl.cli_wrapper:main`) executes the bundled binary
- Works across all platforms where the binary is available

**Why Not setuptools-rust?**
- Simpler build process (no compilation during wheel build)
- Faster CI/CD pipelines (compile once, package many times)
- Better control over build environment and Rust version
- Easier to debug build issues
- Supports cross-compilation workflows

### GitHub Actions Workflow

The `build_on_release.yml` workflow handles automated PyPI publishing:

```yaml
- name: Install Rust toolchain
  uses: dtolnay/rust-toolchain@stable
  with:
    toolchain: 1.83

- name: Cache Cargo registry/index/build
  uses: actions/cache@v4
  # ... caching configuration

- name: Build NoETL
  run: uv build

- name: Publish to PyPI
  env:
    UV_PUBLISH_TOKEN: ${{ secrets.PYPI_TOKEN }}
  run: uv publish
```

## Build Process

1. **UI Build** - Frontend assets compiled via Node.js/npm
2. **Rust Compilation** - Cargo builds `noetl` binary separately in release mode
3. **Binary Packaging** - Copy compiled binary to `noetl/bin/` directory
4. **Python Package** - Setuptools packages Python code, UI assets, and pre-compiled binary
5. **Wheel Creation** - Platform-specific wheel includes binary as package data
6. **PyPI Upload** - `uv publish` uploads wheel to PyPI

**Build Flow:**
```bash
# Step 1: Build UI
cd ui-src && npm ci && npm run build && cd ..
cp -R ui-src/dist/* noetl/core/ui/

# Step 2: Build Rust binary
cd noetlctl && cargo build --release && cd ..

# Step 3: Copy binary to package data
mkdir -p noetl/bin
cp noetlctl/target/release/noetl noetl/bin/noetl
chmod +x noetl/bin/noetl

# Step 4: Build Python package
uv build

# Step 5: Publish to PyPI
uv publish
```

## Platform Support

### Current Support
- **Linux (amd64)** - Primary platform for CI/CD builds
- **macOS (arm64/x86_64)** - Local development support
- **Windows** - Requires additional Rust toolchain setup

### Future: Multi-Platform Wheels

For comprehensive platform coverage, consider using `cibuildwheel`:

```yaml
- name: Build wheels
  uses: pypa/cibuildwheel@v2.22.0
  env:
    CIBW_ARCHS_LINUX: "x86_64 aarch64"
    CIBW_ARCHS_MACOS: "x86_64 arm64"
    CIBW_ARCHS_WINDOWS: "AMD64"
```

This would generate wheels for:
- Linux: x86_64, aarch64
- macOS: Intel (x86_64), Apple Silicon (arm64)
- Windows: AMD64

## Installation Behavior

### With Binary Bundling (Current)
```bash
pip install noetl
noetl --version  # Works immediately - binary included
```

### Without Binary Bundling (Legacy)
```bash
pip install noetl
noetl --version  # Error: command not found
# Would need manual Rust compilation or separate binary distribution
```

## Rust Version Requirements

- **Minimum**: Rust 1.82 (due to `icu` dependency requirements)
- **Recommended**: Rust 1.83 (current CI/CD toolchain)
- **Update Path**: Modify `.github/workflows/build_on_release.yml` and `docker/noetl/dev/Dockerfile`

## Local Development

### Building with Rust Binary
```bash
# Ensure Rust toolchain is installed
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup default 1.83

# Build Python package with Rust binary
uv build

# Install locally
pip install dist/noetl-*.whl
```

### Testing Binary Integration
```bash
# Verify binary is included
python -c "import noetl; import shutil; print(shutil.which('noetl'))"

# Test functionality
noetl --version
noetl server --help
```

## Troubleshooting

### Build Failures

**Rust Compilation Errors:**
```
error: failed to compile `noetl` due to Rust compiler errors
```
- Verify Rust toolchain version: `rustc --version`
- Update Rust: `rustup update`
- Check Cargo.lock compatibility

**Missing setuptools-rust:**
```
ModuleNotFoundError: No module named 'setuptools_rust'
```
- Ensure build dependencies are installed: `pip install setuptools-rust`

### Runtime Issues

**Binary Not Found After Installation:**
```bash
noetl: command not found
```
- Check Python bin directory is in PATH: `echo $PATH`
- Verify installation: `pip show noetl`
- Reinstall: `pip uninstall noetl && pip install noetl`

**Binary Architecture Mismatch:**
```
cannot execute binary file: Exec format error
```
- Platform-specific wheel required
- Install from source: `pip install --no-binary noetl noetl`

## Release Process

1. **Commit Changes** - Push code to `master` branch
2. **Semantic Release** - Analyzes commits, determines version, updates `pyproject.toml`
3. **GitHub Release** - Creates release with tag
4. **Trigger Build** - `build_on_release.yml` workflow activates
5. **Compile Binary** - Rust toolchain compiles `noetl` for target platform
6. **Package Build** - `uv build` creates wheel with embedded binary
7. **PyPI Publish** - `uv publish` uploads to PyPI with authentication token

## Migration Notes

### Phase 1: Binary Integration (Completed)
- ✅ Rust CLI implemented (`noetlctl/src/main.rs`)
- ✅ Docker multi-stage build with Rust compilation
- ✅ Kubernetes deployments using `noetl` binary
- ✅ Local development workflow with `./bin/noetl`

### Phase 2: PyPI Bundling (Current)
- ✅ `setuptools-rust` configuration in `pyproject.toml`
- ✅ GitHub workflow with Rust toolchain setup
- ⏳ Test PyPI release with bundled binary
- ⏳ Verify cross-platform installation

### Phase 3: Python CLI Removal (Planned)
- Remove `noetl/cli/ctl.py` (Python/Typer implementation)
- Update `noetl/main.py` with deprecation notice
- Remove `typer` dependency (if unused elsewhere)
- Update remaining internal references

## References

- [setuptools-rust Documentation](https://setuptools-rust.readthedocs.io/)
- [PyPA: Building Extension Modules](https://packaging.python.org/guides/packaging-binary-extensions/)
- [cibuildwheel](https://cibuildwheel.readthedocs.io/) - Multi-platform wheel building
- [Rust Toolchain Installation](https://rustup.rs/)
