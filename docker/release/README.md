# Release Build Tools

Docker-based tools for building release packages on macOS.

## Build Debian Package

Build `.deb` package using Docker (works on macOS):

```bash
./docker/release/build-deb-docker.sh 2.5.4
```

This will:
1. Build Docker image with build dependencies (Rust, dpkg-dev)
2. Build Debian package inside container
3. Extract `.deb` file to `build/deb/`

Output:
```
build/deb/
├── noetl_2.5.4-1_amd64.deb
└── noetl_2.5.4-1_amd64.deb.sha256
```

## Test Installation

Test the package in a clean Ubuntu container:

```bash
docker run --rm -v $(pwd)/build/deb:/packages ubuntu:22.04 bash -c \
  'apt-get update && dpkg -i /packages/noetl_2.5.4-1_amd64.deb && noetl --version'
```

## Create APT Repository

After building the package, create APT repository structure:

```bash
./scripts/publish_apt.sh 2.5.4
```

This creates `apt-repo/` directory ready for publishing to GitHub Pages.

## Files

- `Dockerfile.deb` - Ubuntu-based builder with Rust and dpkg-dev
- `build-deb-docker.sh` - Main build script that uses Docker
