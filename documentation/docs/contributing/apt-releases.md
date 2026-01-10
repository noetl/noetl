---
sidebar_position: 11
---

# APT Package Release Process

This guide documents the process for publishing NoETL CLI releases as Debian packages via APT repository.

## Overview

NoETL provides `.deb` packages for Ubuntu/Debian distributions, hosted via GitHub Pages as an APT repository. The process involves building packages, creating repository metadata, and publishing to GitHub.

## Prerequisites

- Debian build tools: `dpkg-dev`, `dpkg-deb`
- Rust toolchain for building binary
- Push access to `noetl/noetl` or `noetl/apt` repository
- Linux system for building (can use Docker/GitHub Actions)

## Repository Architecture

Two hosting options:

### Option 1: GitHub Pages on Main Repository
- Branch: `apt` in `noetl/noetl`
- URL: `https://noetl.github.io/noetl`
- Pros: Single repository, simpler management
- Cons: Larger main repo size

### Option 2: Separate APT Repository
- Repository: `noetl/apt` (dedicated)
- URL: `https://noetl.github.io/apt`
- Pros: Cleaner separation, smaller main repo
- Cons: Additional repository to manage

## Build Process

### 1. Build Debian Package

Run the build script on a Linux system or in Docker:

```bash
./scripts/build_deb.sh 2.5.3
```

This script:
- Clones repository at the specified version
- Builds Rust binary with cargo
- Creates debian package structure
- Generates `.deb` file with proper control metadata
- Creates SHA256 checksum

Output:
```
build/deb/noetl_2.5.3-1_amd64.deb
build/deb/noetl_2.5.3-1_amd64.deb.sha256
```

### 2. Create APT Repository

Generate repository metadata:

```bash
./scripts/publish_apt.sh 2.5.3 amd64
```

This creates:
```
apt-repo/
├── dists/
│   ├── jammy/      # Ubuntu 22.04
│   ├── focal/      # Ubuntu 20.04
│   └── noble/      # Ubuntu 24.04
│       └── main/
│           └── binary-amd64/
│               ├── Packages
│               ├── Packages.gz
│               └── Release
└── pool/
    └── main/
        └── noetl_2.5.3-1_amd64.deb
```

### 3. Publish to GitHub Pages

#### For Main Repository (`noetl/noetl`)

```bash
# Create apt branch if doesn't exist
git checkout --orphan apt
git rm -rf .

# Copy repository files
cp -r apt-repo/* .

# Commit and push
git add .
git commit -m "Add NoETL v2.5.3 package"
git push origin apt

# Enable GitHub Pages
# Go to Settings > Pages > Source: apt branch
```

#### For Separate Repository (`noetl/apt`)

```bash
# Clone apt repository
git clone git@github.com:noetl/apt.git
cd apt

# Copy repository files
cp -r ../noetl/apt-repo/* .

# Commit and push
git add .
git commit -m "Add NoETL v2.5.3 package"
git push origin main

# Enable GitHub Pages if not already
# Settings > Pages > Source: main branch
```

### 4. Upload to GitHub Releases

Upload `.deb` and checksum to GitHub releases:

```bash
# Create release (or use GitHub web interface)
gh release create v2.5.3 \
  build/deb/noetl_2.5.3-1_amd64.deb \
  build/deb/noetl_2.5.3-1_amd64.deb.sha256 \
  --title "NoETL v2.5.3" \
  --notes "Release notes here"
```

## Building in Docker

For consistent builds, use Docker:

```bash
# Create Dockerfile for building
cat > Dockerfile.deb-builder <<'EOF'
FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    build-essential \
    dpkg-dev \
    curl \
    git

# Install Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /build
EOF

# Build in container
docker build -f Dockerfile.deb-builder -t noetl-deb-builder .

docker run --rm -v $(pwd):/build noetl-deb-builder \
  bash -c "cd /build && ./scripts/build_deb.sh 2.5.3"
```

## GitHub Actions Automation

Create `.github/workflows/build-deb.yml`:

```yaml
name: Build Debian Package

on:
  push:
    tags:
      - 'v*'

jobs:
  build-deb:
    runs-on: ubuntu-22.04
    
    steps:
      - uses: actions/checkout@v4
      
      - name: Install dependencies
        run: |
          sudo apt-get update
          sudo apt-get install -y dpkg-dev
      
      - name: Setup Rust
        uses: actions-rs/toolchain@v1
        with:
          toolchain: stable
      
      - name: Build package
        run: ./scripts/build_deb.sh ${GITHUB_REF#refs/tags/v}
      
      - name: Create APT repository
        run: ./scripts/publish_apt.sh ${GITHUB_REF#refs/tags/v}
      
      - name: Upload to release
        uses: softprops/action-gh-release@v1
        with:
          files: |
            build/deb/*.deb
            build/deb/*.sha256
      
      - name: Deploy to apt branch
        run: |
          git config user.name "GitHub Actions"
          git config user.email "actions@github.com"
          git checkout --orphan apt-temp
          git rm -rf .
          cp -r apt-repo/* .
          git add .
          git commit -m "Release ${GITHUB_REF#refs/tags/}"
          git branch -D apt || true
          git branch -m apt
          git push -f origin apt
```

## Package Structure

### Control File (`debian/control`)

Defines package metadata and dependencies:

```
Package: noetl
Version: 2.5.3-1
Architecture: amd64
Maintainer: NoETL Team <support@noetl.io>
Description: NoETL workflow automation CLI
Depends: ${shlibs:Depends}
```

### Build Rules (`debian/rules`)

Makefile for building:

```makefile
#!/usr/bin/make -f

override_dh_auto_build:
	cd crates/noetlcli && cargo build --release

override_dh_auto_install:
	install -D -m 0755 target/release/noetl debian/noetl/usr/bin/noetl
```

## Testing

### Test Local Installation

```bash
# Install locally
sudo dpkg -i build/deb/noetl_2.5.3-1_amd64.deb

# Verify
noetl --version

# Test execution
noetl run examples/hello.yaml

# Remove
sudo dpkg -r noetl
```

### Test APT Repository

```bash
# Add local repository
echo "deb [trusted=yes] file://$(pwd)/apt-repo jammy main" | sudo tee /etc/apt/sources.list.d/noetl-test.list

# Update and install
sudo apt-get update
sudo apt-get install noetl

# Verify
noetl --version

# Cleanup
sudo apt-get remove noetl
sudo rm /etc/apt/sources.list.d/noetl-test.list
```

## Multi-Architecture Support

Build for ARM64:

```bash
# Setup cross-compilation
rustup target add aarch64-unknown-linux-gnu
sudo apt-get install gcc-aarch64-linux-gnu

# Build with cargo
export CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER=aarch64-linux-gnu-gcc
cargo build --release --target aarch64-unknown-linux-gnu -p noetl-cli

# Build .deb for arm64
./scripts/build_deb.sh 2.5.3 arm64
```

## Troubleshooting

### Build fails with cargo errors

Ensure Rust is up to date:
```bash
rustup update stable
cargo clean
```

### dpkg-deb not found

Install debian build tools:
```bash
sudo apt-get install dpkg-dev
```

### Repository metadata errors

Regenerate Packages file:
```bash
cd apt-repo
dpkg-scanpackages --arch amd64 pool/ > dists/jammy/main/binary-amd64/Packages
gzip -k -f dists/jammy/main/binary-amd64/Packages
```

## Related Documentation

- [APT Installation Guide](../installation/apt.md)
- [Homebrew Release Process](./homebrew-releases.md)
- [Release Process Overview](./releases.md)
