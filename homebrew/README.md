# Homebrew Installation Guide

## Quick Install

```bash
brew tap noetl/tap
brew install noetl
```

## What Gets Installed

The `noetl` CLI tool provides:
- **Local playbook execution** - Run workflows without server infrastructure
- **Server/worker management** - Start/stop NoETL services
- **Resource management** - Register playbooks and credentials
- **Kubernetes operations** - Deploy to K8s clusters

## Verify Installation

```bash
noetl --version
noetl --help
```

## Quick Start

Create a simple playbook:

```yaml
# hello.yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: hello_world

workflow:
  - step: start
    tool:
      kind: shell
      cmds:
        - "echo 'Hello from NoETL!'"
    next:
      - step: end
  - step: end
```

Run it:

```bash
noetl run hello.yaml
```

## Features

### Local Execution
```bash
# Run entire playbook
noetl run automation/tasks.yaml

# Run specific step/target
noetl run automation/deploy.yaml production

# Pass variables
noetl run tasks.yaml --set env=prod --set version=v2.5.10 --verbose
```

### Server Management
```bash
# Start NoETL server
noetl server start --init-db

# Start worker
noetl worker start

# Stop services
noetl server stop
noetl worker stop
```

### Kubernetes Operations
```bash
# Deploy to kind cluster
noetl k8s deploy

# Redeploy with rebuild
noetl k8s redeploy

# Full reset
noetl k8s reset
```

## Building from Source

If you prefer to build from source:

```bash
git clone https://github.com/noetl/noetl.git
cd noetl
cargo build --release -p noetl-cli
cp target/release/noetl /usr/local/bin/
```

## Documentation

- **Homepage**: https://noetl.io
- **Documentation**: https://noetl.io/docs
- **GitHub**: https://github.com/noetl/noetl
- **PyPI Package**: https://pypi.org/project/noetl-cli/

## Support

- **Issues**: https://github.com/noetl/noetl/issues
- **Discussions**: https://github.com/noetl/noetl/discussions

## License

MIT License - see [LICENSE](https://github.com/noetl/noetl/blob/master/LICENSE)
