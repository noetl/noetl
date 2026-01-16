---
sidebar_position: 10
---

# Release Process

This guide documents the complete release process for publishing NoETL across all distribution channels.

## Overview

NoETL is distributed through multiple channels:
- **Homebrew**: macOS/Linux package manager
- **APT**: Debian/Ubuntu repository at https://noetl.github.io/apt
- **PyPI**: Python package (noetlctl)
- **Crates.io**: Rust package (noetl, noetl-gateway)
- **GitHub Releases**: Binary downloads

## Prerequisites

- `brew` (for Homebrew testing)
- `cargo` and `maturin` (for Rust/Python publishing)
- `dpkg` and `dpkg-dev` (for Debian packages)
- `gh` CLI (for GitHub releases)
- `twine` (for PyPI publishing, optional - maturin handles this)
- Write access to noetl GitHub repositories

## Version Update Process

### 1. Update Version Numbers

Update version in all configuration files:

```bash
# Root workspace Cargo.toml
version = "2.5.5"

# crates/noetlctl/pyproject.toml
version = "2.5.5"

# crates/gateway/Cargo.toml
version = "2.5.5"

# pyproject.toml (root - for noetl Python package)
version = "2.5.5"

# homebrew/noetl.rb (will be updated with SHA256 later)
url = "https://github.com/noetl/noetl/archive/refs/tags/v2.5.5.tar.gz"
```

### 2. Create Release Branch

```bash
git checkout -b release/v2.5.5
git add Cargo.toml crates/*/Cargo.toml crates/*/pyproject.toml pyproject.toml homebrew/noetl.rb
git commit -m "chore: Bump version to 2.5.5"
git push -u origin release/v2.5.5
```

Create and merge PR, then pull to master:

```bash
git checkout master
git pull
```

### 3. Create Git Tag

```bash
git tag -a v2.5.5 -m "Release v2.5.5 - <Brief description>"
git push origin v2.5.5
```

## Build Artifacts

### Build Rust Binary

```bash
cd crates/noetlctl
cargo build --release
# Binary at: ../../target/release/noetl
```

### Build Python Wheel

```bash
cd crates/noetlctl
maturin build --release
# Wheel at: ../../target/wheels/noetlctl-2.5.5-py3-none-macosx_11_0_arm64.whl
```

### Build Debian Package

```bash
./docker/release/build-deb-docker.sh 2.5.5
# Package at: build/deb/noetl_2.5.5-1_arm64.deb
```

Test installation:

```bash
docker run --rm -v $(pwd)/build/deb:/packages ubuntu:22.04 bash -c \
  'apt-get update && dpkg -i /packages/noetl_2.5.5-1_*.deb && noetl --version'
```

## Publishing

### 1. Publish to PyPI (noetlctl)

```bash
cd crates/noetlctl
maturin publish
```

Verify:
```bash
pip install --upgrade noetlctl
noetl --version
```

### 2. Publish to Crates.io

**Main CLI:**
```bash
cd crates/noetlctl
cargo publish
```

**Gateway:**
```bash
cd crates/gateway
cargo publish
```

Verify:
```bash
cargo install noetl
cargo install noetl-gateway
```

### 3. Publish APT Repository

**Build and publish:**

```bash
# Using Docker (recommended)
./docker/release/publish-apt-docker.sh 2.5.5 arm64
```

**Upload to GitHub Pages:**

APT repository is hosted at https://github.com/noetl/apt (public repository):

```bash
# Copy generated repository
cp -r apt-repo/* /path/to/apt-repo/

cd /path/to/apt-repo
git add .
git commit -m "Add NoETL v2.5.5"
git push origin main
```

GitHub Pages automatically deploys from the `main` branch. Repository is accessible at:
```
https://noetl.github.io/apt
```

**Verify installation:**

```bash
echo 'deb [trusted=yes] https://noetl.github.io/apt jammy main' | sudo tee /etc/apt/sources.list.d/noetl.list
sudo apt-get update
sudo apt-get install noetl
noetl --version
```

### 4. Create GitHub Release

```bash
# Create release notes file
cat > release-notes-v2.5.5.md << 'EOF'
# NoETL v2.5.5

## What's New
- Feature highlights
- Bug fixes
- Breaking changes (if any)

## Installation
See https://noetl.dev/docs/getting-started/installation

## Full Changelog
https://github.com/noetl/noetl/compare/v2.5.3...v2.5.5
EOF

# Create release with binary
gh release create v2.5.5 \
  --title "v2.5.5 - <Release Name>" \
  --notes-file release-notes-v2.5.5.md \
  target/release/noetl#noetl-macos-arm64
```

### 5. Update Homebrew Formula

**Calculate SHA256:**

```bash
curl -sL https://github.com/noetl/noetl/archive/refs/tags/v2.5.5.tar.gz | shasum -a 256
```

**Update formula:**

Edit `homebrew/noetl.rb`:

```ruby
url "https://github.com/noetl/noetl/archive/refs/tags/v2.5.5.tar.gz"
sha256 "<calculated_sha256>"
```

**Publish to tap:**

```bash
# Copy to homebrew-tap repository
cp homebrew/noetl.rb /path/to/homebrew-tap/Formula/noetl.rb

cd /path/to/homebrew-tap
git add Formula/noetl.rb
git commit -m "Update noetl to v2.5.5"
git push
```

**Verify installation:**

```bash
brew update
brew upgrade noetl
noetl --version
```

## Verification Checklist

After publishing, verify all channels:

- [ ] **PyPI**: `pip install --upgrade noetlctl && noetl --version`
- [ ] **Crates.io**: `cargo install noetl && noetl --version`
- [ ] **Homebrew**: `brew upgrade noetl && noetl --version`
- [ ] **APT**: Visit https://noetl.github.io/apt and check Packages file
- [ ] **GitHub Release**: Check https://github.com/noetl/noetl/releases/tag/v2.5.5
- [ ] **Documentation**: Update version references in docs

## Common Issues

### dpkg-scanpackages Not Found

Install dpkg-dev:
```bash
brew install dpkg  # macOS
```

Or use Docker-based publishing:
```bash
./docker/release/publish-apt-docker.sh 2.5.5 arm64
```

### Homebrew Caching Old Version

Clear cache and reinstall:
```bash
brew update
brew upgrade noetl
# If still showing old version:
brew uninstall noetl
brew install noetl
```

### Version Mismatch in venv

If using Python virtual environment with noetlctl:
```bash
pip install --upgrade --force-reinstall noetlctl
```

### PyPI Upload Credentials

maturin uses credentials from `~/.pypirc`:

```ini
[pypi]
username = __token__
password = pypi-...
```

## Post-Release

1. Update documentation version references
2. Announce release on social media/blog
3. Update CHANGELOG.md
4. Close milestone (if using GitHub milestones)
5. Archive release branch (optional)

## Rollback Procedure

If a release has critical issues:

1. **GitHub**: Delete release and tag
2. **PyPI**: Cannot delete, publish hotfix version (e.g., 2.5.5.post1)
3. **Crates.io**: Yank version: `cargo yank noetl@2.5.5`
4. **Homebrew**: Revert commit in homebrew-tap
5. **APT**: Remove version from apt repository

## Automation

Consider automating the release process with GitHub Actions:

```yaml
# .github/workflows/release.yml
name: Release
on:
  push:
    tags:
      - 'v*'
jobs:
  release:
    runs-on: ubuntu-latest
    steps:
      - name: Build artifacts
      - name: Publish to PyPI
      - name: Publish to Crates.io
      - name: Create GitHub release
      - name: Update Homebrew formula
```

## Related Documentation

- [Installation Guide](../getting-started/installation.md)
- [APT Installation](../installation/apt.md)
- [Homebrew Installation](../installation/homebrew.md)
