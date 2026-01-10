---
sidebar_position: 4
---

# Cargo/Crates.io Installation

Install NoETL CLI from the official Rust package registry (crates.io).

## Quick Install

```bash
cargo install noetl
```

This installs the `noetl` binary to `~/.cargo/bin/` (ensure it's in your PATH).

## Prerequisites

### Install Rust

If you don't have Rust installed:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source ~/.cargo/env
```

Verify installation:

```bash
cargo --version
rustc --version
```

## Installation Options

### Latest Stable Version

```bash
cargo install noetl-cli
```

### Specific Version

```bash
cargo install noetl --version 2.5.3
```

### From Git (Development)

Install the latest development version:

```bash
cargo install --git https://github.com/noetl/noetl noetl
```

### From Local Source

If you have the repository cloned:

```bash
cd noetl/crates/noetlctl
cargo install --path .
```

## Verify Installation

```bash
noetl --version
# Output: noetl 2.5.3

noetl --help
```

## Update

```bash
cargo install noetl --force
```

The `--force` flag reinstalls even if already installed.

## Uninstall

```bash
cargo uninstall noetl
```

## Build Options

### Optimized Build

For maximum performance:

```bash
cargo install noetl --profile release-lto
```

## Package Details

**Crate Name**: `noetl` (on crates.io)  
**Directory**: `crates/noetlctl` (in repository)  
**PyPI Package**: `noetlctl` (Python distribution)  
**Binary Name**: `noetl` (installed command)

This naming allows:
- Clean cargo install: `cargo install noetl`
- Descriptive directory: `noetlctl` = "noetl control"
- Separate Python package: `pip install noetlctl`

### Minimal Binary Size

```bash
cargo install noetl-cli --profile min-size
```

### With Debug Symbols

```bash
cargo install noetl-cli --profile release --debug
```

## Cross-Platform Installation

### Linux (amd64)

```bash
cargo install noetl-cli --target x86_64-unknown-linux-gnu
```

### Linux (arm64)

```bash
rustup target add aarch64-unknown-linux-gnu
cargo install noetl-cli --target aarch64-unknown-linux-gnu
```

### macOS (Intel)

```bash
cargo install noetl-cli --target x86_64-apple-darwin
```

### macOS (Apple Silicon)

```bash
cargo install noetl-cli --target aarch64-apple-darwin
```

## Package Information

- **Crate Name**: `noetl-cli`
- **Binary Name**: `noetl`
- **Registry**: https://crates.io/crates/noetl-cli
- **Documentation**: https://docs.rs/noetl-cli

## Alternative Installation Methods

- **Homebrew** (macOS): `brew install noetl`
- **APT** (Ubuntu/Debian): `sudo apt-get install noetl`
- **PyPI**: `pip install noetl-cli`
- **Docker**: `docker pull ghcr.io/noetl/noetl:latest`

## Troubleshooting

### Cargo not found

Ensure Rust is installed and `~/.cargo/bin` is in your PATH:

```bash
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

For zsh:

```bash
echo 'export PATH="$HOME/.cargo/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Compilation fails

Update Rust to the latest stable version:

```bash
rustup update stable
rustup default stable
```

### Permission denied

If you get permission errors, ensure `~/.cargo/bin` is writable:

```bash
chmod +x ~/.cargo/bin/noetl
```

### Binary not in PATH

Find where cargo installed the binary:

```bash
which noetl
# If not found, check:
ls ~/.cargo/bin/noetl
```

Add to PATH if needed:

```bash
export PATH="$HOME/.cargo/bin:$PATH"
```

### Build takes too long

Use a faster linker (Linux):

```bash
# Install mold linker
sudo apt-get install mold
# or
cargo install mold

# Use it for installation
RUSTFLAGS="-C link-arg=-fuse-ld=mold" cargo install noetl-cli
```

## Next Steps

- [Quick Start Guide](../getting-started/quickstart.md)
- [Local Playbook Execution](../noetlctl/local-execution.md)
- [Configuration](../configuration/overview.md)
