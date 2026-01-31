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
    
    # Copy UI build to Python package
    echo "Copying UI assets to noetl/core/ui/..."
    mkdir -p "${REPO_ROOT}/noetl/core/ui"
    rm -rf "${REPO_ROOT}/noetl/core/ui"/*
    cp -r dist/* "${REPO_ROOT}/noetl/core/ui/"
    
    echo -e "${GREEN}UI assets built successfully${NC}"
else
    echo -e "${YELLOW}Skipping UI build (ui-src not found)${NC}"
    echo "Creating placeholder directory to disable UI..."
    mkdir -p "${REPO_ROOT}/noetl/core/ui/assets"
fi

echo

# Build Rust CLI
if [ -d "${REPO_ROOT}/noetlctl" ]; then
    echo -e "${GREEN}Building Rust CLI binary...${NC}"
    cd "${REPO_ROOT}/noetlctl"
    
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
    echo -e "${YELLOW}Skipping Rust CLI build (noetlctl not found)${NC}"
fi

echo
echo -e "${GREEN}Local development setup complete!${NC}"
echo
echo "Quick start:"
echo "  1. Start server: ./bin/noetl server start"
echo "  2. Or directly:  python -m noetl.server --host 0.0.0.0 --port 8082"
echo "  3. Start worker: ./bin/noetl worker start"
echo
echo "Environment variables:"
echo "  export NOETL_ENABLE_UI=false  # Disable UI if not needed"
echo "  export NOETL_DB_URL=...       # Database connection"
echo
echo "For Docker/K8s development:"
echo "  noetl run automation/boot.yaml                    # Complete K8s setup"
echo "  noetl run automation/development/docker.yaml      # Build container images"
