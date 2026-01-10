# NoETL APT Repository

This is an APT package repository for NoETL CLI.

## Installation

```bash
echo "deb [trusted=yes] https://noetl.github.io/noetl jammy main" | sudo tee /etc/apt/sources.list.d/noetl.list
sudo apt-get update
sudo apt-get install noetl
```

## Supported Ubuntu Versions
- Ubuntu 24.04 (Noble)
- Ubuntu 22.04 (Jammy)
- Ubuntu 20.04 (Focal)

## Architecture
- ARM64 (Apple Silicon, Raspberry Pi, AWS Graviton)

