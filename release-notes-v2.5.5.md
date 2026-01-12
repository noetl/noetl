# NoETL v2.5.5 Release Notes

## What's New

### Automation Framework
Complete infrastructure-as-code automation for local development with 12 playbooks covering 133+ actions:
- Bootstrap: Complete setup with prerequisite validation
- Infrastructure: PostgreSQL, Kind cluster, ClickHouse, Qdrant, NATS, VictoriaMetrics monitoring
- Development: Docker, dev tools, JupyterLab
- Gateway: Gateway server and UI
- Testing: Pagination test server

See [automation documentation](https://noetl.dev/docs/development/automation_playbooks) for details.

## Installation

### Homebrew (macOS)
```bash
brew tap noetl/tap
brew install noetl
```

### APT (Ubuntu/Debian)
```bash
echo 'deb [trusted=yes] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list
sudo apt-get update
sudo apt-get install noetl
```

### PyPI
```bash
pip install noetlctl
```

### Cargo
```bash
cargo install noetl
```

## Documentation

Full documentation: [noetl.dev](https://noetl.dev)

## Assets

- `noetl` - macOS ARM64 binary
- Source code (zip)
- Source code (tar.gz)
