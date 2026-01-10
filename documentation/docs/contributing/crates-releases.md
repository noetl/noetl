---
sidebar_position: 12
---

# Crates.io Release Process

This guide documents the process for publishing NoETL CLI to crates.io, the official Rust package registry.

## Overview

The `noetl` crate is published to https://crates.io/crates/noetl, allowing users to install via `cargo install noetl`.

**Note**: The crate name is `noetl` (directory: `crates/noetlctl`, PyPI: `noetlctl`).

## Prerequisites

- **crates.io Account**: https://crates.io/
- **API Token**: Generate at https://crates.io/settings/tokens
- **Cargo Ownership**: Must be added as owner of `noetl-cli` crate
- **Workspace Version**: Ensure version is updated in root `Cargo.toml`

## Setup

### 1. Create crates.io Account

1. Visit https://crates.io/
2. Sign in with GitHub account
3. Verify email address

### 2. Generate API Token

1. Go to https://crates.io/settings/tokens
2. Click "New Token"
3. Name: `noetl-publish`
4. Permissions: `publish-update`
5. Copy the generated token

### 3. Configure Cargo

```bash
# Login with token
cargo login <your-token>

# Or set environment variable
export CARGO_REGISTRY_TOKEN=<your-token>
```

Token is stored in `~/.cargo/credentials.toml`.

## Package Preparation

### 1. Update Cargo.toml Metadata

Ensure `crates/noetlctl/Cargo.toml` has all required fields:

```toml
[package]
name = "noetl"
version.workspace = true
edition.workspace = true
license.workspace = true
repository.workspace = true
homepage.workspace = true
description = "NoETL workflow automation CLI"
keywords = ["workflow", "automation", "etl", "mlops", "data-pipeline"]
categories = ["command-line-utilities", "development-tools"]
readme = "README.md"
```

Required fields for crates.io:
- `description` - Short package description
- `license` - License identifier (e.g., "MIT")
- `repository` - GitHub repository URL
- `keywords` - Up to 5 keywords for discoverability
- `categories` - Crates.io categories
- `readme` - Path to README file

### 2. Update README

Ensure `crates/noetlctl/README.md` is user-friendly:
- Installation instructions
- Quick start example
- Feature highlights
- Link to full documentation

### 3. Update Workspace Version

```toml
# Cargo.toml (workspace root)
[workspace.package]
version = "2.5.3"
```
**Important**: The crate name is `noetl` but the directory is `crates/noetlctl` and PyPI package is `noetlctl`. This naming scheme allows:
- Clean cargo install: `cargo install noetl`
- Consistent directory naming: `noetlctl` = "noetl control"
- Separate PyPI namespace: `pip install noetlctl`
## Publication Process

### Manual Publication

```bash
# Navigate to crate directory
cd crates/noetlctl

# Verify package builds
cargo build --release

# Dry run (verify packaging)
cargo publish --dry-run

# Publish to crates.io
cargo publish
```

### Using Publish Script

```bash
# From repository root
./scripts/publish_crate.sh 2.5.3
```

The script will:
1. Verify API token is configured
2. Check required metadata fields
3. Build the package
4. Run dry-run validation
5. Prompt for confirmation
6. Publish to crates.io

## Verification

### Check Publication Status

```bash
# View package on crates.io
open https://crates.io/crates/noetl-cli

# Test installation
cargo install noetl-cli --force
noetl --version
```

### Monitor Downloads

View statistics at:
- https://crates.io/crates/noetl-cli
- https://crates.io/crates/noetl-cli/stats

## Versioning

### Version Numbers

Follow semantic versioning (SemVer):
- **Major** (X.0.0): Breaking changes
- **Minor** (0.X.0): New features, backwards compatible
- **Patch** (0.0.X): Bug fixes, backwards compatible

### Yanking Versions

If a version has critical bugs:

```bash
# Yank version (prevents new installs, doesn't break existing)
cargo yank --vers 2.5.2

# Un-yank if mistake
cargo yank --vers 2.5.2 --undo
```

## Workspace Publishing

Since `noetl-cli` is in a workspace:

1. **Publish order matters**: No dependencies on other workspace members
2. **Version sync**: Use `version.workspace = true`
3. **Shared metadata**: Use `license.workspace = true`, etc.

If publishing multiple crates:

```bash
# Publish in dependency order
cargo publish -p noetl-cli
# cargo publish -p gateway  # if needed
```

## Automation with GitHub Actions

Create `.github/workflows/publish-crate.yml`:

```yaml
name: Publish to crates.io

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Rust
        uses: actions-rs/toolchain@v1
        with:
          toolchain: stable
      
      - name: Verify version
        run: |
          TAG_VERSION=${GITHUB_REF#refs/tags/v}
          CARGO_VERSION=$(grep '^version' Cargo.toml | head -1 | cut -d'"' -f2)
          if [ "$TAG_VERSION" != "$CARGO_VERSION" ]; then
            echo "Version mismatch: tag=$TAG_VERSION, cargo=$CARGO_VERSION"
            exit 1
          fi
      
      - name: Publish to crates.io
        env:
          CARGO_REGISTRY_TOKEN: ${{ secrets.CARGO_REGISTRY_TOKEN }}
        run: |
          cd crates/noetlctl
          cargo publish
```

Add `CARGO_REGISTRY_TOKEN` to repository secrets:
1. Go to repository Settings > Secrets and variables > Actions
2. New repository secret
3. Name: `CARGO_REGISTRY_TOKEN`
4. Value: Your crates.io API token

## Best Practices

### Pre-Release Checklist

- [ ] Update version in workspace `Cargo.toml`
- [ ] Update CHANGELOG.md
- [ ] Test build: `cargo build --release -p noetl-cli`
- [ ] Run tests: `cargo test -p noetl-cli`
- [ ] Update README if needed
- [ ] Run `cargo publish --dry-run`
- [ ] Create Git tag: `git tag v2.5.3`
- [ ] Push tag: `git push origin v2.5.3`

### Post-Release

- [ ] Verify package appears on crates.io
- [ ] Test installation: `cargo install noetl-cli --force`
- [ ] Update documentation with new version
- [ ] Announce release (GitHub Releases, blog, etc.)

### Documentation

Update docs.rs documentation by creating `crates/noetlctl/.cargo-ok` or using:

```toml
[package.metadata.docs.rs]
all-features = true
rustdoc-args = ["--cfg", "docsrs"]
```

## Troubleshooting

### "crate already exists"

Version already published. Increment version number.

### "failed to verify permissions"

Not listed as crate owner. Ask existing owner to add you:

```bash
cargo owner --add github:username noetl-cli
```

### "license is not specified"

Add to Cargo.toml:

```toml
license = "MIT"
# or
license-file = "LICENSE"
```

### "package size exceeds limit"

Crates.io has 10MB limit. Exclude unnecessary files:

```toml
# Cargo.toml
[package]
exclude = [
    "tests/",
    "benches/",
    "examples/",
    ".github/",
    "*.log",
]
```

### Build fails on crates.io

Ensure all dependencies are from crates.io (not git):

```toml
# Bad: git dependency
dependency = { git = "https://..." }

# Good: crates.io dependency
dependency = "1.0"
```

## Related Documentation

- [Cargo Installation Guide](../installation/cargo.md)
- [Homebrew Release Process](./homebrew-releases.md)
- [APT Release Process](./apt-releases.md)
- [Cargo Book: Publishing on crates.io](https://doc.rust-lang.org/cargo/reference/publishing.html)
