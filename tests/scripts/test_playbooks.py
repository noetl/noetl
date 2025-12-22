#!/usr/bin/env python3
"""
Test NoETL playbooks one by one
"""
import yaml
import requests
import json
import time
from pathlib import Path

BASE_URL = "http://localhost:8082"

def register_playbook(yaml_path):
    """Register a playbook from YAML file"""
    with open(yaml_path) as f:
        content = f.read()
        data = yaml.safe_load(content)
    
    path = data['metadata']['path']
    payload = {'path': path, 'content': content}
    response = requests.post(f'{BASE_URL}/api/catalog/register', json=payload)
    return response.status_code, response.json(), path

def execute_playbook(path, payload_data=None):
    """Execute a playbook"""
    exec_payload = {'path': path, 'payload': payload_data or {}}
    response = requests.post(f'{BASE_URL}/api/execute', json=exec_payload)
    return response.status_code, response.json()

def get_execution_events(execution_id):
    """Get events for an execution"""
    query = f"""
    SELECT event_type, node_name, status, error 
    FROM noetl.event 
    WHERE execution_id = {execution_id} 
    ORDER BY event_id
    """
    response = requests.post(f'{BASE_URL}/api/postgres/execute', json={'query': query})
    result = response.json()
    if result.get('status') == 'ok':
        return result['result']
    return []

def test_playbook(yaml_path, description, wait_time=3):
    """Test a single playbook"""
    print("\n" + "=" * 70)
    print(f"TEST: {description}")
    print("=" * 70)
    print(f"File: {yaml_path}")
    
    try:
        # Register
        status, result, path = register_playbook(yaml_path)
        print(f"\n✓ Registration: {status}")
        if status != 200:
            print(f"  ERROR: {result}")
            return False
        
        # Execute
        status, result = execute_playbook(path)
        print(f"✓ Execution: {status}")
        if status != 200:
            print(f"  ERROR: {result}")
            return False
        
        execution_id = result.get('execution_id')
        print(f"  Execution ID: {execution_id}")
        
        # Wait for completion
        time.sleep(wait_time)
        
        # Check events
        events = get_execution_events(execution_id)
        print(f"\n  Events ({len(events)}):")
        
        has_error = False
        for event_type, node_name, status, error in events:
            if error:
                has_error = True
                print(f"    ❌ {event_type:20} {node_name or 'N/A':25} {status or 'N/A'}")
                print(f"       ERROR: {error[:100]}")
            else:
                symbol = "✓" if status == 'COMPLETED' else "→"
                print(f"    {symbol} {event_type:20} {node_name or 'N/A':25} {status or 'N/A'}")
        
        # Check final result
        if events:
            last_event = events[-1]
            if last_event[0] == 'playbook.completed' and not has_error:
                print(f"\n✅ PASSED: {description}")
                return True
            else:
                print(f"\n❌ FAILED: {description}")
                return False
        else:
            print(f"\n❌ FAILED: No events found")
            return False
            
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all playbook tests"""
    tests = [
        # Basic tests
        ('tests/fixtures/playbooks/v2_simple_python.yaml', 'v2_simple_python', 3),
        ('tests/fixtures/playbooks/v2_actions_test.yaml', 'v2_actions_test', 5),
        
        # Control flow tests
        ('tests/fixtures/playbooks/v2_loop_test.yaml', 'v2_loop_test', 5),
        ('tests/fixtures/playbooks/iterator_save_test.yaml', 'iterator_save_test', 5),
        
        # HTTP tests
        ('tests/fixtures/playbooks/v2_http_test.yaml', 'v2_http_test', 5),
        
        # Database tests
        ('tests/fixtures/playbooks/v2_postgres_test.yaml', 'v2_postgres_test', 5),
        ('tests/fixtures/playbooks/v2_duckdb_test.yaml', 'v2_duckdb_test', 5),
        
        # Examples
        ('tests/fixtures/playbooks/examples/simple_http_v2.yaml', 'simple_http_v2', 5),
        ('tests/fixtures/playbooks/examples/weather_loop_v2.yaml', 'weather_loop_v2', 10),
    ]
    
    results = []
    for test_args in tests:
        if len(test_args) == 3:
            yaml_path, description, wait_time = test_args
        else:
            yaml_path, description = test_args
            wait_time = 3
        
        passed = test_playbook(yaml_path, description, wait_time)
        results.append((description, passed))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for description, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {description}")
    
    passed_count = sum(1 for _, p in results if p)
    total_count = len(results)
    print(f"\nTotal: {passed_count}/{total_count} passed")

if __name__ == '__main__':
    main()
