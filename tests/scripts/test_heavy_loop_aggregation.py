#!/usr/bin/env python3
"""
Heavy Loop Aggregation Test Script

Tests the NATS K/V refactoring by running a loop with many items
and verifying result aggregation works correctly.

Usage:
    python tests/scripts/test_heavy_loop_aggregation.py [--items N] [--padding N]

Arguments:
    --items N     Number of items to process (default: 100)
    --padding N   Result padding size in bytes (default: 100)
"""

import argparse
import json
import time
import yaml
import httpx
import sys

BASE_URL = "http://localhost:8082"
PLAYBOOK_PATH = "tests/fixtures/playbooks/load_test/heavy_loop_aggregation/heavy_loop_aggregation.yaml"


def register_playbook():
    """Register the playbook with the server."""
    with open(PLAYBOOK_PATH, 'r') as f:
        playbook = yaml.safe_load(f)

    response = httpx.post(
        f"{BASE_URL}/api/catalog/register",
        json={"content": json.dumps(playbook)},
        timeout=30.0
    )

    if response.status_code != 200:
        print(f"Registration failed: {response.status_code} - {response.text}")
        return None

    print(f"Registration: {response.status_code}")
    return playbook


def execute_playbook(playbook, item_count: int, padding_size: int):
    """Execute the playbook with custom parameters."""
    payload = {}
    if item_count != 100 or padding_size != 100:
        payload = {
            "workload": {
                "item_count": item_count,
                "result_padding_size": padding_size
            }
        }

    response = httpx.post(
        f"{BASE_URL}/api/execute",
        json={
            "path": playbook['metadata']['path'],
            "payload": payload
        },
        timeout=30.0
    )

    if response.status_code != 200:
        print(f"Execution failed: {response.status_code} - {response.text}")
        return None

    execution_id = response.json().get('execution_id')
    print(f"Execution ID: {execution_id}")
    print(f"Processing {item_count} items with {padding_size} bytes padding...")
    return execution_id


def wait_for_completion(execution_id: int, timeout: int = 300):
    """Wait for the playbook to complete."""
    start_time = time.time()
    check_interval = 2  # seconds

    while time.time() - start_time < timeout:
        response = httpx.post(
            f"{BASE_URL}/api/postgres/execute",
            json={
                "query": f"""
                    SELECT event_type, node_name, status, result
                    FROM noetl.event
                    WHERE execution_id = {execution_id}
                    ORDER BY event_id DESC
                    LIMIT 50
                """,
                "schema": "noetl"
            },
            timeout=30.0
        )

        if response.status_code != 200:
            time.sleep(check_interval)
            continue

        events = response.json().get('result', [])

        # Check for completion
        for event in events:
            event_type = event[0] if isinstance(event, list) else event.get('event_type')
            if event_type in ('playbook_completed', 'playbook.completed'):
                return True, events
            if event_type in ('playbook_failed', 'playbook.failed', 'workflow.failed'):
                return False, events

        elapsed = time.time() - start_time
        print(f"  Waiting... ({elapsed:.0f}s elapsed, {len(events)} events)")
        time.sleep(check_interval)

    return False, []


def get_loop_events(execution_id: int):
    """Get loop iteration events for analysis."""
    response = httpx.post(
        f"{BASE_URL}/api/postgres/execute",
        json={
            "query": f"""
                SELECT COUNT(*) as iteration_count
                FROM noetl.event
                WHERE execution_id = {execution_id}
                  AND loop_name = 'process_items'
                  AND event_type = 'step.exit'
            """,
            "schema": "noetl"
        },
        timeout=30.0
    )

    if response.status_code == 200:
        result = response.json().get('result', [])
        if result:
            return result[0][0] if isinstance(result[0], list) else result[0].get('iteration_count', 0)
    return 0


def get_aggregation_result(execution_id: int):
    """Get the aggregation result from the validate_results step."""
    response = httpx.post(
        f"{BASE_URL}/api/postgres/execute",
        json={
            "query": f"""
                SELECT result
                FROM noetl.event
                WHERE execution_id = {execution_id}
                  AND node_name = 'validate_results'
                  AND event_type = 'step.exit'
                  AND result IS NOT NULL
                ORDER BY event_id DESC
                LIMIT 1
            """,
            "schema": "noetl"
        },
        timeout=30.0
    )

    if response.status_code == 200:
        result = response.json().get('result', [])
        if result:
            raw = result[0][0] if isinstance(result[0], list) else result[0].get('result')
            if isinstance(raw, str):
                return json.loads(raw)
            return raw
    return None


def main():
    parser = argparse.ArgumentParser(description='Run heavy loop aggregation test')
    parser.add_argument('--items', type=int, default=100, help='Number of items to process')
    parser.add_argument('--padding', type=int, default=100, help='Result padding size in bytes')
    parser.add_argument('--timeout', type=int, default=300, help='Timeout in seconds')
    args = parser.parse_args()

    print("=" * 60)
    print("HEAVY LOOP AGGREGATION TEST")
    print("=" * 60)
    print(f"Items: {args.items}")
    print(f"Padding: {args.padding} bytes")
    print(f"Timeout: {args.timeout}s")
    print("=" * 60)

    # Register playbook
    playbook = register_playbook()
    if not playbook:
        sys.exit(1)

    # Execute playbook
    execution_id = execute_playbook(playbook, args.items, args.padding)
    if not execution_id:
        sys.exit(1)

    # Wait for completion
    print("\nWaiting for completion...")
    success, events = wait_for_completion(execution_id, args.timeout)

    # Get results
    loop_iterations = get_loop_events(execution_id)
    validation_result = get_aggregation_result(execution_id)

    # Print results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"Loop iterations completed: {loop_iterations}")

    if validation_result:
        print(f"Status: {validation_result.get('status', 'unknown')}")
        print(f"All checks passed: {validation_result.get('all_checks_passed', False)}")

        validations = validation_result.get('validations', [])
        if validations:
            print("\nValidation checks:")
            for v in validations:
                status = "PASS" if v.get('passed') else "FAIL"
                print(f"  [{status}] {v.get('check')}: {v.get('message')}")

        perf = validation_result.get('performance', {})
        if perf:
            print(f"\nPerformance:")
            print(f"  Processing time: {perf.get('processing_time_seconds', 'N/A')}s")
            print(f"  Items/second: {perf.get('items_per_second', 'N/A')}")

    print("\n" + "=" * 60)
    if success and validation_result and validation_result.get('all_checks_passed'):
        print("TEST PASSED")
        print("=" * 60)
        sys.exit(0)
    else:
        print("TEST FAILED")
        print("=" * 60)
        sys.exit(1)


if __name__ == '__main__':
    main()
