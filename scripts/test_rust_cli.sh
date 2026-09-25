#!/bin/bash
# Test Rust CLI server start functionality
# This script tests if the Rust CLI can successfully invoke the Python server

set -e

echo "Testing NoETL Rust CLI Server Start"
echo "===================================="
echo

# Test 1: Check binary exists and is executable
echo "✓ Test 1: Binary exists"
if [ -x "./bin/noetl" ]; then
    echo "  Binary found at ./bin/noetl"
    ./bin/noetl --version
else
    echo "  ✗ Binary not found or not executable"
    exit 1
fi
echo

# Test 2: Check server command help
echo "✓ Test 2: Server command available"
noetl server start --help | head -3
echo

# Test 3: Check if port 8082 is available
echo "✓ Test 3: Port availability check"
if lsof -i :8082 >/dev/null 2>&1; then
    echo "  ⚠ Port 8082 is already in use (likely K8s cluster)"
    echo "  The Rust CLI would fail with 'Port already in use' error"
    echo "  To test locally, stop the K8s server or use a different port via env vars"
else
    echo "  ✓ Port 8082 is available"
    echo "  Ready to start server"
fi
echo

# Test 4: Show how to start server
echo "✓ Test 4: Server start command"
echo "  Command: noetl server start"
echo "  This command will:"
echo "    1. Start the Rust noetl-server (https://github.com/noetl/server)"
echo "    2. Run it in the background (daemon)"
echo "    3. Save PID to ~/.noetl/noetl_server.pid"
echo

# Test 5: the CLI is the Rust binary; the Python server module was retired in
# 25bef859 and the implementation now lives in https://github.com/noetl/server.
# This probed `python -m noetl.server`, which can never succeed again, so the
# script exited 1 unconditionally.
echo "✓ Test 5: CLI is the Rust binary"
if command -v noetl >/dev/null 2>&1; then
    echo "  ✓ noetl on PATH: $(noetl --version 2>/dev/null || echo unknown)"
else
    echo "  ✗ noetl not on PATH - install the CLI (pip install noetl, or cargo install)"
    exit 1
fi
echo

echo "===================================="
echo "Summary: Rust CLI is working correctly"
echo
echo "To start the server:"
echo "  1. Stop K8s cluster if running: kind delete cluster --name noetl"
echo "  2. Start local server: ./bin/noetl server start"
echo "  3. Check status: curl http://localhost:8082/health"
echo "  4. Stop server: ./bin/noetl server stop"
echo
echo "Note: Port 8082 is currently used by K8s. Use K8s for testing or"
echo "      stop the cluster to test local server."
