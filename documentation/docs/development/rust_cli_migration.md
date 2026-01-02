---
sidebar_position: 10
---

# Rust CLI Migration Plan

## Overview

This document outlines the plan to migrate the NoETL Python CLI (`noetl/cli/ctl.py`) to a Rust-based CLI (`noetlctl` → `noetl`) and bundle it with the Python package for distribution via PyPI.

## Goals

1. **Replace Python CLI with Rust** - Migrate all server/worker management commands from Python Typer CLI to Rust Clap CLI
2. **Rename binary** - Change `noetlctl` to `noetl` as the primary executable name
3. **Bundle with PyPI package** - Include pre-compiled Rust binaries for all major platforms when users `pip install noetl`
4. **Cross-platform support** - Build for multiple architectures (x86_64, aarch64) on Linux, macOS, Windows
5. **Remove Python CLI** - Delete `noetl/cli/ctl.py` and related Python CLI code once migration is complete

## Current State

### Python CLI (noetl/cli/ctl.py)
Commands currently implemented in Python Typer:

**Server Management:**
- `noetl server start [--init-db]` - Start FastAPI server with Uvicorn/Gunicorn
  - Reads config from environment (host, port, workers, reload, debug, enable_ui)
  - Manages PID file (`~/.noetl/noetl_server.pid`)
  - Port conflict detection
  - Database initialization (optional)
  - Spawns subprocess with proper environment variables
- `noetl server stop [--force]` - Stop running server by PID or port detection

**Worker Management:**
- `noetl worker start [--max-workers N] [--v2]` - Start worker pool
  - v1: ScalableQueueWorkerPool (asyncio-based polling)
  - v2: Event-driven NATS architecture
  - Manages PID files (`~/.noetl/noetl_worker_{name}.pid`)
  - Signal handling (SIGTERM, SIGINT)
- `noetl worker stop [--name NAME] [--force]` - Stop worker by name or list/select

**Database Management:**
- `noetl db init` - Initialize database schema
- `noetl db validate` - Validate database schema
- Other db commands...

**Entry Point:**
- `pyproject.toml`: `noetl = "noetl.main:main"`
- `noetl/main.py`: Imports and runs `cli_app` from `noetl.cli.ctl`

### Rust CLI (noetlctl/src/main.rs)
Commands currently implemented in Rust Clap:

**Catalog Management:**
- `noetlctl catalog register <path>` - Register playbook/credential from YAML file
- `noetlctl catalog get <path>` - Get resource details
- `noetlctl catalog list <type>` - List resources by type

**Execution:**
- `noetlctl execute playbook <path> [--input <file>]` - Execute playbook

**Credentials:**
- `noetlctl credential get <name> [--include-data]` - Get credential details

**SQL Query:**
- `noetlctl query "<sql>" [--schema <name>] [--format table|json]` - Execute SQL queries

**Status:**
- `noetlctl status` - Get server status

**TUI:**
- `noetlctl tui` - Interactive terminal UI

## Migration Steps

### Phase 1: Rename Binary and Add Server/Worker Commands

#### 1.1 Rename noetlctl to noetl
- [ ] Update `noetlctl/Cargo.toml`: Change `name = "noetlctl"` to `name = "noetl"`
- [ ] Update README references from `noetlctl` to `noetl`
- [ ] Update all internal documentation

#### 1.2 Add Server Management Commands
- [ ] Implement `noetl server start [--init-db]`
  - Spawn Python server subprocess: `python -m uvicorn noetl.server:create_app --factory`
  - Pass environment variables from config
  - Manage PID file creation/cleanup
  - Port conflict detection
  - Optional database initialization via REST API call
- [ ] Implement `noetl server stop [--force]`
  - Read PID from `~/.noetl/noetl_server.pid`
  - Send SIGTERM, wait for graceful shutdown (10s timeout)
  - Optional SIGKILL with `--force`
  - Port-based fallback if PID file missing

#### 1.3 Add Worker Management Commands
- [ ] Implement `noetl worker start [--max-workers N] [--v2]`
  - Spawn Python worker subprocess with proper environment
  - Support v1 (default) and v2 (--v2 flag) architectures
  - Manage PID file (`~/.noetl/noetl_worker_{name}.pid`)
  - Pass max-workers to Python if specified
- [ ] Implement `noetl worker stop [--name NAME] [--force]`
  - List available workers if --name not provided
  - Interactive selection from list
  - SIGTERM → SIGKILL escalation
  - PID file cleanup

#### 1.4 Add Database Commands
- [ ] Implement `noetl db init` - Call REST API `/api/db/init` or spawn Python subprocess
- [ ] Implement `noetl db validate` - Call REST API or subprocess
- [ ] Consider other db commands from Python CLI

### Phase 2: Bundle Rust Binary with Python Package

#### 2.1 Setup setuptools-rust
```toml
# pyproject.toml additions
[build-system]
requires = ["setuptools>=45", "wheel", "setuptools-rust>=1.9.0"]
build-backend = "setuptools.build_meta"

[tool.setuptools-rust]
# Renamed from noetlctl to noetl
[[tool.setuptools-rust.bins]]
name = "noetl"
path = "noetlctl/src/main.rs"
```

#### 2.2 Update setup.py (if needed)
Create `setup.py` if not exists for setuptools-rust integration:
```python
from setuptools import setup
from setuptools_rust import Bin, RustExtension

setup(
    rust_extensions=[
        Bin("noetl", path="noetlctl/Cargo.toml"),
    ],
    zip_safe=False,
)
```

#### 2.3 Cross-Platform Compilation
Options for building wheels for multiple platforms:

**Option A: cibuildwheel (Recommended)**
- Use GitHub Actions with `cibuildwheel`
- Automatically builds wheels for:
  - Linux: x86_64, aarch64 (via QEMU)
  - macOS: x86_64 (Intel), arm64 (Apple Silicon)
  - Windows: x86_64
- `.github/workflows/build-wheels.yml`:
  ```yaml
  name: Build Wheels
  on: [push, pull_request]
  jobs:
    build_wheels:
      name: Build wheels on ${{ matrix.os }}
      runs-on: ${{ matrix.os }}
      strategy:
        matrix:
          os: [ubuntu-22.04, macos-13, macos-14, windows-2022]
      steps:
        - uses: actions/checkout@v4
        - uses: dtolnay/rust-toolchain@stable
        - name: Build wheels
          uses: pypa/cibuildwheel@v2.16.5
          env:
            CIBW_BUILD: "cp312-*"
            CIBW_ARCHS_LINUX: "x86_64 aarch64"
            CIBW_ARCHS_MACOS: "x86_64 arm64"
            CIBW_ARCHS_WINDOWS: "AMD64"
        - uses: actions/upload-artifact@v4
          with:
            name: wheels-${{ matrix.os }}
            path: ./wheelhouse/*.whl
  ```

**Option B: Manual cross-compilation**
- Linux: Use `cross` crate for cross-compilation
- macOS: Use `cargo build --target x86_64-apple-darwin` and `--target aarch64-apple-darwin`
- Windows: Use `cargo build --target x86_64-pc-windows-gnu`

#### 2.4 PyPI Distribution
- [ ] Update version in both `Cargo.toml` and `pyproject.toml` to match
- [ ] Build wheels with setuptools-rust: `python -m build`
- [ ] Test installation: `pip install dist/noetl-*.whl`
- [ ] Verify `noetl` binary in PATH after install
- [ ] Publish to PyPI: `twine upload dist/*`

### Phase 3: Remove Python CLI

#### 3.1 Remove Python CLI Code
- [ ] Delete `noetl/cli/ctl.py`
- [ ] Delete `noetl/cli/__init__.py` (if empty)
- [ ] Update `noetl/main.py` to print message directing users to Rust CLI
- [ ] Remove Typer dependency from `pyproject.toml` (keep if used elsewhere)

#### 3.2 Update Documentation
- [ ] Update all READMEs with new `noetl` command examples
- [ ] Update `documentation/docs/` with Rust CLI usage
- [ ] Update taskfile.yml tasks to use `noetl` instead of Python CLI
- [ ] Update test fixtures and integration tests

#### 3.3 Deprecation Path
**Option A: Immediate removal** (breaking change)
- Bump major version (3.0.0)
- Document migration in CHANGELOG.md

**Option B: Gradual deprecation** (safer)
- Keep Python CLI for 1-2 versions with deprecation warnings
- Show message: "Python CLI is deprecated, use Rust CLI instead"
- Remove in version 3.0.0

## Implementation Details

### Rust CLI Structure

```rust
// noetlctl/src/main.rs additions

#[derive(Subcommand)]
enum ServerCommand {
    /// Start NoETL server
    Start {
        /// Initialize database schema on startup
        #[arg(long)]
        init_db: bool,
    },
    /// Stop NoETL server
    Stop {
        /// Force stop without confirmation
        #[arg(short, long)]
        force: bool,
    },
}

#[derive(Subcommand)]
enum WorkerCommand {
    /// Start NoETL worker pool
    Start {
        /// Maximum number of worker threads
        #[arg(short = 'm', long)]
        max_workers: Option<usize>,
        
        /// Use v2 worker architecture (event-driven NATS)
        #[arg(long)]
        v2: bool,
    },
    /// Stop NoETL worker
    Stop {
        /// Worker name to stop
        #[arg(short = 'n', long)]
        name: Option<String>,
        
        /// Force stop without confirmation
        #[arg(short, long)]
        force: bool,
    },
}

#[derive(Subcommand)]
enum DbCommand {
    /// Initialize database schema
    Init,
    /// Validate database schema
    Validate,
}

// Add to main Commands enum
#[derive(Subcommand)]
enum Commands {
    // ... existing commands ...
    
    /// Server management
    Server {
        #[command(subcommand)]
        command: ServerCommand,
    },
    
    /// Worker management
    Worker {
        #[command(subcommand)]
        command: WorkerCommand,
    },
    
    /// Database management
    Db {
        #[command(subcommand)]
        command: DbCommand,
    },
}
```

### Process Management Strategy

**Server Start:**
```rust
async fn start_server(init_db: bool) -> Result<()> {
    // 1. Read config from environment or config file
    // 2. Check for existing PID file
    // 3. Check port availability
    // 4. Spawn Python server subprocess
    let mut cmd = Command::new("python");
    cmd.args(&["-m", "uvicorn", "noetl.server:create_app", "--factory"])
       .args(&["--host", &host, "--port", &port])
       .env("NOETL_ENABLE_UI", &enable_ui)
       // ... other env vars
       .stdout(Stdio::piped())
       .stderr(Stdio::piped());
    
    let child = cmd.spawn()?;
    
    // 5. Write PID file
    fs::write(pid_path, child.id().to_string())?;
    
    // 6. Optional: Call init-db REST API if flag set
    if init_db {
        // Wait for server to be ready
        wait_for_server(&base_url, Duration::from_secs(30)).await?;
        // Call /api/db/init
        client.post(&format!("{}/api/db/init", base_url)).send().await?;
    }
    
    Ok(())
}
```

**Process Stop:**
```rust
fn stop_process(pid_path: &Path, force: bool) -> Result<()> {
    // 1. Read PID from file
    let pid = fs::read_to_string(pid_path)?.trim().parse()?;
    
    // 2. Check if process exists
    if !process_exists(pid)? {
        eprintln!("Process {} not found", pid);
        fs::remove_file(pid_path)?;
        return Ok(());
    }
    
    // 3. Confirm unless force
    if !force {
        print!("Stop process {}? [y/N]: ", pid);
        // ... confirmation logic
    }
    
    // 4. Send SIGTERM
    send_signal(pid, Signal::SIGTERM)?;
    
    // 5. Wait for graceful shutdown (10s)
    for _ in 0..20 {
        if !process_exists(pid)? {
            fs::remove_file(pid_path)?;
            return Ok(());
        }
        thread::sleep(Duration::from_millis(500));
    }
    
    // 6. Force kill if still running
    if force || confirm_force_kill() {
        send_signal(pid, Signal::SIGKILL)?;
    }
    
    fs::remove_file(pid_path)?;
    Ok(())
}
```

### Dependencies to Add

```toml
# noetlctl/Cargo.toml
[dependencies]
# ... existing ...
nix = "0.27"  # For Unix signals (SIGTERM, SIGKILL)
sysinfo = "0.30"  # For process management
tokio = { version = "1", features = ["process", "time"] }
```

## Testing Strategy

### Unit Tests
- [ ] Test PID file creation/deletion
- [ ] Test process spawning with correct arguments
- [ ] Test signal handling (SIGTERM, SIGKILL)
- [ ] Test environment variable propagation

### Integration Tests
- [ ] Test full server start/stop cycle
- [ ] Test full worker start/stop cycle
- [ ] Test with v1 and v2 worker architectures
- [ ] Test init-db flag functionality
- [ ] Test port conflict detection

### Cross-Platform Tests
- [ ] Test on Linux (x86_64, aarch64)
- [ ] Test on macOS (Intel, Apple Silicon)
- [ ] Test on Windows (x86_64)
- [ ] Verify binary bundling in wheels for all platforms

## Rollout Plan

### Version 2.5.0 (Parallel Existence)
- Add server/worker commands to Rust CLI
- Keep Python CLI functional
- Add deprecation warnings to Python CLI
- Update documentation to show both options

### Version 2.6.0 (Transition)
- Make Rust CLI the default recommendation
- Python CLI shows migration notice
- Bundle Rust binary with PyPI package

### Version 3.0.0 (Breaking Change)
- Remove Python CLI entirely
- `noetl` command is Rust binary only
- Update all documentation

## Risk Mitigation

### Risks
1. **Cross-platform compilation complexity** - Different behavior on Windows vs Unix
2. **Python subprocess management** - Process lifecycle, environment passing
3. **Backwards compatibility** - Existing scripts/tools using Python CLI
4. **PyPI wheel distribution** - Large binary sizes, platform-specific wheels

### Mitigation Strategies
1. **Comprehensive testing** - CI/CD for all target platforms
2. **Feature parity verification** - Checklist to ensure no regression
3. **Gradual rollout** - Deprecation period for Python CLI
4. **Fallback mechanism** - Document Python CLI usage for emergency rollback

## Success Criteria

- [ ] Rust CLI has 100% feature parity with Python CLI for server/worker management
- [ ] `pip install noetl` installs working `noetl` binary on Linux/macOS/Windows
- [ ] Binary works on x86_64 and aarch64 architectures
- [ ] All integration tests pass with Rust CLI
- [ ] Documentation updated with Rust CLI examples
- [ ] No performance regression in server/worker startup
- [ ] Binary size < 20MB (optimized release build)

## Timeline Estimate

- **Phase 1** (Rust CLI commands): 3-5 days
- **Phase 2** (PyPI bundling): 2-3 days
- **Phase 3** (Cleanup & testing): 2-3 days
- **Total**: 7-11 days

## References

- setuptools-rust: https://github.com/PyO3/setuptools-rust
- cibuildwheel: https://cibuildwheel.readthedocs.io/
- Clap command-line parser: https://docs.rs/clap/
- Process management in Rust: https://docs.rs/sysinfo/
