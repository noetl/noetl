#!/usr/bin/env python3
"""
OAuth Playbooks Test Runner
Tests GCS and Secret Manager OAuth integrations
"""

import requests
import json
import time
from datetime import datetime

NOETL_SERVER = "http://localhost:8082"

def test_playbook(name, playbook_path, playbook_file, validation_node):
    """Test a single OAuth playbook"""
    print(f"\n{'='*60}")
    print(f"Testing: {name}")
    print(f"{'='*60}")
    
    # Read playbook
    print(f"Reading playbook: {playbook_file}")
    with open(playbook_file, 'r') as f:
        playbook_content = f.read()
    
    # Register playbook
    print(f"Registering playbook: {playbook_path}")
    response = requests.post(
        f"{NOETL_SERVER}/api/catalog/register",
        json={
            'path': playbook_path,
            'content': playbook_content
        }
    )
    result = response.json()
    print(f"  Status: {result.get('status')}")
    print(f"  Version: {result.get('version')}")
    
    if result.get('status') != 'success':
        print(f"  ❌ Registration failed: {result}")
        return False
    
    # Execute playbook
    print(f"Executing playbook...")
    response = requests.post(
        f"{NOETL_SERVER}/api/run/playbook",
        json={'path': playbook_path}
    )
    result = response.json()
    execution_id = result.get('execution_id')
    
    if not execution_id:
        print(f"  ❌ Failed to start execution: {result}")
        return False
    
    print(f"  Execution ID: {execution_id}")
    
    # Wait for completion
    print(f"Waiting for execution to complete...")
    time.sleep(20)
    
    # Query events
    query = f"""
    SELECT node_name, event_type
    FROM noetl.event
    WHERE execution_id = {execution_id}
    ORDER BY event_id
    """
    
    response = requests.post(
        f"{NOETL_SERVER}/api/postgres/execute",
        json={'query': query, 'schema': 'noetl'}
    )
    events = response.json().get('result', [])
    print(f"  Total Events: {len(events)}")
    
    # Validate result
    query = f"""
    SELECT result->'status', result->'data'->'status_code'
    FROM noetl.event
    WHERE execution_id = {execution_id}
      AND node_name = '{validation_node}'
      AND event_type = 'action_completed'
    """
    
    response = requests.post(
        f"{NOETL_SERVER}/api/postgres/execute",
        json={'query': query, 'schema': 'noetl'}
    )
    
    result = response.json().get('result', [])
    if result:
        status = result[0][0]
        code = result[0][1]
        print(f"  API Status: {status}")
        print(f"  HTTP Code: {code}")
        
        if code == 200:
            print(f"  ✅ PASSED - OAuth working")
            return True
        else:
            print(f"  ⚠️ Completed with HTTP {code}")
            return False
    else:
        print(f"  ❌ No result found for node: {validation_node}")
        return False

def main():
    """Run all OAuth tests"""
    print(f"OAuth Playbooks Test Runner")
    print(f"Time: {datetime.now()}")
    print(f"Server: {NOETL_SERVER}")
    
    results = {}
    
    # Test GCS OAuth
    results['GCS'] = test_playbook(
        name="Google Cloud Storage OAuth",
        playbook_path="tests/fixtures/playbooks/oauth/google_gcs",
        playbook_file="tests/fixtures/playbooks/oauth/google_gcs/gcs_oauth.yaml",
        validation_node="list_buckets"
    )
    
    # Test Secret Manager OAuth
    results['Secret Manager'] = test_playbook(
        name="Google Secret Manager OAuth",
        playbook_path="tests/fixtures/playbooks/oauth/google_secret_manager",
        playbook_file="tests/fixtures/playbooks/oauth/google_secret_manager/secret_manager_oauth.yaml",
        validation_node="call_secret_manager_api"
    )
    
    # Summary
    print(f"\n{'='*60}")
    print(f"TEST SUMMARY")
    print(f"{'='*60}")
    for name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"  {name}: {status}")
    
    all_passed = all(results.values())
    print(f"\nOverall: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    exit(main())
