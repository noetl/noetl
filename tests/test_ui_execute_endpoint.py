#!/usr/bin/env python3
"""
Test script to validate the UI execute endpoint fix.

This script tests the complete flow:
1. Schema validation with different field name variants
2. Endpoint routing and registration
3. Backward compatibility with legacy fields

Run: .venv/bin/python3 tests/test_ui_execute_endpoint.py
"""

import sys
from noetl.server.api.run.schema import ExecutionRequest
from noetl.server.api.run import router


def test_schema_field_normalization():
    """Test that all field name variants are properly normalized."""
    print("\n=== Testing Schema Field Normalization ===")
    
    tests = [
        {
            "name": "input_payload normalization",
            "data": {
                "path": "test/path",
                "version": "1",
                "input_payload": {"key": "value"}
            },
            "expected_args": {"key": "value"}
        },
        {
            "name": "parameters alias",
            "data": {
                "path": "test/path",
                "version": "1",
                "parameters": {"key2": "value2"}
            },
            "expected_args": {"key2": "value2"}
        },
        {
            "name": "args direct",
            "data": {
                "path": "test/path",
                "version": "1",
                "args": {"key3": "value3"}
            },
            "expected_args": {"key3": "value3"}
        },
        {
            "name": "catalog_id with input_payload",
            "data": {
                "catalog_id": "123456789",
                "input_payload": {"test": "data"}
            },
            "expected_args": {"test": "data"}
        },
        {
            "name": "with legacy sync_to_postgres field (should be ignored)",
            "data": {
                "path": "test/path",
                "input_payload": {"key": "value"},
                "sync_to_postgres": True,
                "merge": False
            },
            "expected_args": {"key": "value"}
        }
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            req = ExecutionRequest(**test["data"])
            if req.args == test["expected_args"]:
                print(f"✓ {test['name']}: PASSED")
                passed += 1
            else:
                print(f"✗ {test['name']}: FAILED - Expected {test['expected_args']}, got {req.args}")
                failed += 1
        except Exception as e:
            print(f"✗ {test['name']}: FAILED - {e}")
            failed += 1
    
    return passed, failed


def test_endpoint_registration():
    """Test that the /execute endpoint is properly registered."""
    print("\n=== Testing Endpoint Registration ===")
    
    routes = {}
    for route in router.routes:
        if hasattr(route, 'path') and hasattr(route, 'methods'):
            method = list(route.methods)[0] if route.methods else "GET"
            routes[route.path] = method
    
    required_endpoints = {
        "/run/{resource_type}": "POST",
        "/execute": "POST"
    }
    
    passed = 0
    failed = 0
    
    for path, method in required_endpoints.items():
        if path in routes:
            if routes[path] == method:
                print(f"✓ {method} {path}: REGISTERED")
                passed += 1
            else:
                print(f"✗ {method} {path}: FAILED - Method mismatch (found {routes[path]})")
                failed += 1
        else:
            print(f"✗ {method} {path}: FAILED - Not registered")
            failed += 1
    
    print("\nAll registered routes:")
    for path, method in routes.items():
        print(f"  {method} {path}")
    
    return passed, failed


def test_ui_request_format():
    """Test the exact format sent by the UI."""
    print("\n=== Testing UI Request Format ===")
    
    # This is the exact format from the error log
    ui_request = {
        "path": "tests/control-flow/end_with_action",
        "version": "1",
        "sync_to_postgres": True,
        "merge": False,
        "input_payload": {"pg_auth": "pg_local"}
    }
    
    try:
        req = ExecutionRequest(**ui_request)
        print("✓ UI request format: ACCEPTED")
        print(f"  Normalized args: {req.args}")
        print(f"  Path: {req.path}")
        print(f"  Version: {req.version}")
        print(f"  Merge: {req.merge}")
        return 1, 0
    except Exception as e:
        print(f"✗ UI request format: FAILED - {e}")
        return 0, 1


def main():
    """Run all tests and report results."""
    print("\n" + "="*60)
    print("UI Execute Endpoint Fix - Validation Tests")
    print("="*60)
    
    total_passed = 0
    total_failed = 0
    
    # Run schema tests
    passed, failed = test_schema_field_normalization()
    total_passed += passed
    total_failed += failed
    
    # Run endpoint registration tests
    passed, failed = test_endpoint_registration()
    total_passed += passed
    total_failed += failed
    
    # Run UI format test
    passed, failed = test_ui_request_format()
    total_passed += passed
    total_failed += failed
    
    # Summary
    print("\n" + "="*60)
    print(f"SUMMARY: {total_passed} passed, {total_failed} failed")
    print("="*60)
    
    if total_failed > 0:
        print("\n⚠ Some tests failed. Please review the errors above.")
        sys.exit(1)
    else:
        print("\n✓ All tests passed! The fix is working correctly.")
        sys.exit(0)


if __name__ == "__main__":
    main()
