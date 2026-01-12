# NoETL

**NoETL** is an automation framework for orchestrating **APIs, databases, and scripts** using a declarative **Playbook DSL**.

Execution is standardized around an **MCP-style tool model**: consistent tool contracts, structured input/output, and a predictable lifecycle. From an MCP perspective, `tools` include API endpoints, database operations, and scripts/utilities **NoETL** orchestrates and optimizes them via playbooks.

With **NoETL Gateway**, playbooks can be deployed as a **distributed backend**: developers ship business logic as playbooks, and UIs/clients call stable endpoints without deploying dedicated microservices for each workflow.

[![PyPI version](https://badge.fury.io/py/noetl.svg)](https://badge.fury.io/py/noetl)

## Documentation

**https://noetl.dev**

## Distribution channels

- **PyPI**
  - `noetl` (Python): https://pypi.org/project/noetl/
  - `noetlctl` (Rust CLI): https://pypi.org/project/noetlctl/
- **crates.io**
  - `noetl`: https://crates.io/crates/noetl
  - `noetl-gateway`: https://crates.io/crates/noetl-gateway
- **APT (Debian/Ubuntu)**
  - Repo: https://github.com/noetl/apt
- **Homebrew**
  - Tap: https://github.com/noetl/homebrew-tap

## License

MIT License — see [LICENSE](LICENSE) for details.
