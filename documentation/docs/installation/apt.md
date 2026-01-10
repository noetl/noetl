---
sidebar_position: 3
---

# APT Installation (Ubuntu/Debian)

Install NoETL CLI on Ubuntu and Debian-based Linux distributions using APT package manager.

## Quick Install

Add NoETL APT repository and install:

```bash
# Add repository (using GitHub Pages as repository host)
echo 'deb [trusted=yes] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list

# Update package index
sudo apt-get update

# Install noetl
sudo apt-get install noetl
```

## Supported Distributions

- Ubuntu 24.04 (Noble) - use codename `noble`
- Ubuntu 22.04 (Jammy) - use codename `jammy`
- Ubuntu 20.04 (Focal) - use codename `focal`
- Debian-based distributions compatible with Ubuntu packages

## Verify Installation

```bash
noetl --version
# Output: noetl 2.5.4

noetl --help
```

## Update

```bash
sudo apt-get update
sudo apt-get upgrade noetl
```

## Uninstall

```bash
sudo apt-get remove noetl
sudo rm /etc/apt/sources.list.d/noetl.list
```

## Manual Installation from .deb File

Download and install the .deb package directly:

```bash
# Download from GitHub releases
wget https://github.com/noetl/noetl/releases/download/v2.5.4/noetl_2.5.4-1_amd64.deb

# Verify checksum (optional)
wget https://github.com/noetl/noetl/releases/download/v2.5.4/noetl_2.5.4-1_amd64.deb.sha256
sha256sum -c noetl_2.5.4-1_amd64.deb.sha256

# Install
sudo dpkg -i noetl_2.5.4-1_amd64.deb

# Fix dependencies if needed
sudo apt-get install -f
```

## Architecture Support

- `amd64` (x86_64) - Intel/AMD 64-bit
- `arm64` (aarch64) - ARM 64-bit (coming soon)

## What Gets Installed

The package installs:
- `/usr/bin/noetl` - Main CLI binary

Features:
- **Local playbook execution** - Run workflows without server infrastructure
- **Server/worker management** - Start/stop NoETL services
- **Resource management** - Register playbooks and credentials
- **Kubernetes operations** - Deploy to K8s clusters
- **Database management** - Initialize and validate schema

## Alternative Installation Methods

- **Homebrew** (macOS): `brew install noetl`
- **Crates.io**: `cargo install noetl`
- **PyPI**: `pip install noetlctl`
- **Docker**: `docker pull ghcr.io/noetl/noetl:latest`
- **Build from source**: See [Building from Source](./build-from-source.md)

## Troubleshooting

### GPG key verification errors

If you encounter GPG errors, use `[trusted=yes]` option:

```bash
echo 'deb [trusted=yes] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list
```

For production use with GPG signing (coming soon):

```bash
# Import GPG key
curl -fsSL https://noetl.io/apt/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/noetl.gpg

# Add repository with signed key
echo 'deb [signed-by=/usr/share/keyrings/noetl.gpg] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list
```

### Package not found

Ensure you're using the correct codename for your Ubuntu version:

```bash
# Check your Ubuntu version
lsb_release -sc
# Output: jammy (22.04), focal (20.04), noble (24.04)

# Use that codename in repository URL
echo 'deb [trusted=yes] https://noetl.github.io/apt $(lsb_release -sc) main' | sudo tee /etc/apt/sources.list.d/noetl.list
```

### Dependency errors after dpkg install

If manual dpkg installation fails with missing dependencies:

```bash
sudo apt-get install -f
```

### Permission denied

Ensure the binary has execute permissions:

```bash
sudo chmod +x /usr/bin/noetl
```

## Next Steps

- [Quick Start Guide](../getting-started/quickstart.md)
- [Local Playbook Execution](../noetlctl/local-execution.md)
- [Configuration](../configuration/overview.md)
