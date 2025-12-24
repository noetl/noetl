#!/usr/bin/env python3
"""Quick regression test runner"""
import requests
import time
import sys
import logging

logger = logging.getLogger(__name__)

NOETL_SERVER = "http://localhost:8082"
MASTER_TEST_PATH = "tests/fixtures/playbooks/regression_test/master_regression_test"

logger.info(f"Starting regression test at {NOETL_SERVER}...")
try:
    response = requests.post(
        f"{NOETL_SERVER}/api/execute",
        json={"path": MASTER_TEST_PATH, "payload": {}},
        timeout=30
    )
    response.raise_for_status()
    
    result = response.json()
    execution_id = result["execution_id"]
    
    logger.info(f"✓ Test started: execution_id = {execution_id}")
    logger.info(f"  Status: {result['status']}")
    logger.info(f"\nWaiting 2 minutes for test execution...")
    
    # Wait for test to complete (52 playbooks take time)
    time.sleep(120)
    
    # Check status
    logger.info(f"\nChecking execution status...")
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
    logger.info(f"  Steps completed: {stats[0]}")
    logger.info(f"  Total events: {stats[1]}")
    logger.info(f"  Failures: {stats[2]}")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"EXECUTION_ID = {execution_id}")
    logger.info(f"{'='*60}")
    logger.info(f"\nRun regression_dashboard.ipynb with this execution_id to see detailed results")
    
except Exception as e:
    logger.info(f"✗ Error: {e}")
    sys.exit(1)
