#!/bin/bash
# Setup local development environment for NoETL
# Builds UI assets and Rust CLI binary for native architecture

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo -e "${YELLOW}NoETL Local Development Setup${NC}"
echo "This script will:"
echo "  1. Build UI assets (if ui-src exists)"
echo "  2. Build Rust CLI binary for your architecture"
echo "  3. Set up environment for local Python server development"
echo

# Detect architecture
ARCH=$(uname -m)
OS=$(uname -s)

echo -e "${GREEN}Detected: ${OS} ${ARCH}${NC}"
echo

# Build UI assets
if [ -d "${REPO_ROOT}/ui-src" ]; then
    echo -e "${GREEN}Building UI assets...${NC}"
    cd "${REPO_ROOT}/ui-src"
    
    if ! command -v npm &> /dev/null; then
        echo -e "${RED}Error: npm is not installed${NC}"
        echo "Install Node.js to build UI assets or disable UI with: export NOETL_ENABLE_UI=false"
        exit 1
    fi
    
    if [ ! -d "node_modules" ]; then
        echo "Installing UI dependencies..."
        npm install
    fi
    
    echo "Building UI (Vite)..."
    npm run build
    
    echo -e "${GREEN}UI built${NC} (the noetl/core/ui/ copy target went with the"
    echo "Python platform in 25bef859; the UI now lives in https://github.com/noetl/gui)"
else
    echo -e "${YELLOW}Skipping UI build${NC} — ui-src was removed from this repo in"
    echo "e06ed7d2; the UI lives in https://github.com/noetl/gui"
fi

echo

# Build Rust CLI
CLI_DIR="${NOETL_CLI_REPO:-${REPO_ROOT}/../cli}"
if [ -d "${CLI_DIR}" ]; then
    echo -e "${GREEN}Building Rust CLI binary...${NC}"
    cd "${CLI_DIR}"
    
    if ! command -v cargo &> /dev/null; then
        echo -e "${RED}Error: cargo is not installed${NC}"
        echo "Install Rust from https://rustup.rs/"
        exit 1
    fi
    
    echo "Building for native architecture (${ARCH})..."
    cargo build --release
    
    # Copy binary to bin directory
    mkdir -p "${REPO_ROOT}/bin"
    cp target/release/noetl "${REPO_ROOT}/bin/noetl"
    chmod +x "${REPO_ROOT}/bin/noetl"
    
    # Also copy to noetl/bin for bundled distribution
    mkdir -p "${REPO_ROOT}/noetl/bin"
    cp target/release/noetl "${REPO_ROOT}/noetl/bin/noetl"
    chmod +x "${REPO_ROOT}/noetl/bin/noetl"
    
    echo -e "${GREEN}Rust CLI built successfully${NC}"
    echo "Binary location: ${REPO_ROOT}/bin/noetl"
else
    echo -e "${YELLOW}Skipping Rust CLI build (CLI repo not found at ${CLI_DIR})${NC}"
    echo "Clone https://github.com/noetl/cli next to this repo or set NOETL_CLI_REPO."
fi

echo
echo -e "${GREEN}Local development setup complete!${NC}"
echo
echo "Quick start (the server and worker are Rust services now):"
echo "  1. Start server: ./bin/noetl server start   # https://github.com/noetl/server"
echo "  2. Start worker: ./bin/noetl worker start   # https://github.com/noetl/worker"
echo
echo "Environment variables:"
echo "  export NOETL_ENABLE_UI=false  # Disable UI if not needed"
echo "  export NOETL_DB_URL=...       # Database connection"
echo
echo "For Docker/K8s development:"
echo "  noetl run ../ops/automation/boot.yaml                    # Complete K8s setup"
echo "  noetl run ../ops/automation/development/docker.yaml      # Build container images"
