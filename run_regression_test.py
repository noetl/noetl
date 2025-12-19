#!/usr/bin/env python3
"""Quick regression test runner"""
import requests
import time
import sys

NOETL_SERVER = "http://localhost:8082"
MASTER_TEST_PATH = "tests/fixtures/playbooks/regression_test/master_regression_test"

print(f"Starting regression test at {NOETL_SERVER}...")
try:
    response = requests.post(
        f"{NOETL_SERVER}/api/v2/execute",
        json={"path": MASTER_TEST_PATH, "payload": {}},
        timeout=30
    )
    response.raise_for_status()
    
    result = response.json()
    execution_id = result["execution_id"]
    
    print(f"✓ Test started: execution_id = {execution_id}")
    print(f"  Status: {result['status']}")
    print(f"\nWaiting 2 minutes for test execution...")
    
    # Wait for test to complete (52 playbooks take time)
    time.sleep(120)
    
    # Check status
    print(f"\nChecking execution status...")
    query_response = requests.post(
        f"{NOETL_SERVER}/api/postgres/execute",
        json={
            "query": f"""
                SELECT 
                    COUNT(DISTINCT node_name) as steps_completed,
                    COUNT(*) as total_events,
                    COUNT(CASE WHEN event_type = 'playbook_failed' THEN 1 END) as failures
                FROM noetl.event 
                WHERE execution_id = {execution_id}
            """,
            "schema": "noetl"
        }
    )
    
    stats = query_response.json()["result"][0]
    print(f"  Steps completed: {stats[0]}")
    print(f"  Total events: {stats[1]}")
    print(f"  Failures: {stats[2]}")
    
    print(f"\n{'='*60}")
    print(f"EXECUTION_ID = {execution_id}")
    print(f"{'='*60}")
    print(f"\nRun regression_dashboard.ipynb with this execution_id to see detailed results")
    
except Exception as e:
    print(f"✗ Error: {e}")
    sys.exit(1)
