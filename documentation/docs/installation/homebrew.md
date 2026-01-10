---
sidebar_position: 2
---

# Homebrew Installation

Install NoETL CLI on macOS using Homebrew for easy package management and automatic updates.

## Quick Install

```bash
brew tap noetl/tap
brew install noetl
```

## Verify Installation

```bash
noetl --version
# Output: noetl 2.5.3

noetl --help
```

## What Gets Installed

The `noetl` binary provides:
- **Local playbook execution** - Run workflows without server infrastructure
- **Server/worker management** - Start/stop NoETL services locally
- **Resource management** - Register playbooks and credentials
- **Kubernetes operations** - Deploy to K8s clusters
- **Database management** - Initialize and validate schema

## Update

```bash
brew update
brew upgrade noetl
```

## Uninstall

```bash
brew uninstall noetl
brew untap noetl/tap
```

## Build from Source

If you prefer to build from source or need the latest development version:

```bash
git clone https://github.com/noetl/noetl.git
cd noetl
cargo build --release -p noetl
cp target/release/noetl /usr/local/bin/
```

## Alternative Installation Methods

- **PyPI**: `pip install noetlctl` (Python-based distribution)
- **Crates.io**: `cargo install noetl` (Rust-based distribution)
- **APT**: `sudo apt-get install noetl` (Ubuntu/Debian)
- **Docker**: `docker pull ghcr.io/noetl/noetl:latest`
- **Manual**: Download binaries from [GitHub Releases](https://github.com/noetl/noetl/releases)

## Next Steps

- [Quick Start Guide](../getting-started/quickstart.md)
- [Local Playbook Execution](../noetlctl/local-execution.md)
- [Configuration](../configuration/overview.md)

## Troubleshooting

### Command not found after install

If `noetl` command is not found after installation, ensure Homebrew's bin directory is in your PATH:

```bash
echo 'export PATH="/opt/homebrew/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Version conflicts with PyPI package

If you have both Homebrew and PyPI versions installed, pyenv/virtualenv may take precedence:

```bash
# Check which noetl is being used
which noetl

# Use Homebrew version explicitly
/opt/homebrew/bin/noetl --version

# Or uninstall PyPI version
pip uninstall noetlctl
```

### Building from source fails

Ensure you have Rust installed:

```bash
brew install rust
# or
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
```
