#!/usr/bin/env python3
"""Test OAuth integrations for Google GCS and Secret Manager."""

import requests
import json
import time
from pathlib import Path

NOETL_SERVER = "http://localhost:8082"
BASE_PATH = Path(__file__).parent

def register_and_run(playbook_name, playbook_path, playbook_file, wait_time=20):
    """Register and execute a playbook."""
    print(f"\n▶ Testing: {playbook_name}")
    print(f"  Registering playbook...")
    
    # Read playbook content
    full_path = BASE_PATH / playbook_file
    if not full_path.exists():
        print(f"  ✗ Playbook file not found: {playbook_file}")
        return None
    
    with open(full_path, 'r') as f:
        content = f.read()
    
    # Register playbook
    response = requests.post(
        f"{NOETL_SERVER}/api/catalog/register",
        json={'path': playbook_path, 'content': content}
    )
    
    if response.status_code != 200:
        print(f"  ✗ Registration failed: {response.text}")
        return None
    
    result = response.json()
    status = result.get('status')
    version = result.get('version')
    
    if status != 'success':
        print(f"  ✗ Registration failed: {result}")
        return None
    
    print(f"  ✓ Registered: version {version}")
    print(f"  Executing playbook...")
    
    # Execute playbook
    response = requests.post(
        f"{NOETL_SERVER}/api/run/playbook",
        json={'path': playbook_path}
    )
    
    if response.status_code != 200:
        print(f"  ✗ Execution failed: {response.text}")
        return None
    
    result = response.json()
    execution_id = result.get('execution_id')
    
    if not execution_id:
        print(f"  ✗ No execution ID: {result}")
        return None
    
    print(f"  Execution ID: {execution_id}")
    print(f"  Waiting {wait_time}s for completion...")
    time.sleep(wait_time)
    
    return execution_id

def check_api_result(execution_id, node_name, api_name):
    """Check API call result."""
    query = f"""
    SELECT result->'status', result->'data'->'status_code'
    FROM noetl.event
    WHERE execution_id = {execution_id}
      AND node_name = '{node_name}'
      AND event_type = 'action_completed'
    """
    
    response = requests.post(
        f"{NOETL_SERVER}/api/postgres/execute",
        json={'query': query, 'schema': 'noetl'}
    )
    
    if response.status_code != 200:
        return 'unknown', 0
    
    result = response.json().get('result', [])
    if result and len(result) > 0:
        status = result[0][0] if result[0][0] else 'unknown'
        code = result[0][1] if result[0][1] else 0
        return status, code
    
    return 'unknown', 0

def main():
    """Run OAuth tests."""
    print("=== OAuth Integration Tests ===")
    print(f"Server: {NOETL_SERVER}\n")
    
    results = {}
    
    # Test 1: Google GCS
    exec_id = register_and_run(
        "Google Cloud Storage OAuth",
        "tests/fixtures/playbooks/oauth/google_gcs",
        "tests/fixtures/playbooks/oauth/google_gcs/google_gcs_oauth.yaml",
        wait_time=20
    )
    
    if exec_id:
        status, code = check_api_result(exec_id, 'list_buckets', 'GCS API')
        print(f"  GCS API Status: {status} (HTTP {code})")
        results['gcs'] = code
        
        if code == 200:
            print(f"  ✅ Google GCS OAuth Test PASSED")
        else:
            print(f"  ⚠️  Google GCS OAuth Test: HTTP {code}")
    else:
        results['gcs'] = 0
    
    # Test 2: Google Secret Manager
    exec_id = register_and_run(
        "Google Secret Manager OAuth",
        "tests/fixtures/playbooks/oauth/google_secret_manager",
        "tests/fixtures/playbooks/oauth/google_secret_manager/google_secret_manager.yaml",
        wait_time=15
    )
    
    if exec_id:
        status, code = check_api_result(exec_id, 'call_secret_manager_api', 'Secret Manager API')
        print(f"  Secret Manager API Status: {status} (HTTP {code})")
        results['secret_manager'] = code
        
        if code == 200:
            print(f"  ✅ Google Secret Manager OAuth Test PASSED")
        else:
            print(f"  ⚠️  Google Secret Manager OAuth Test: HTTP {code}")
    else:
        results['secret_manager'] = 0
    
    # Summary
    print("\n=== OAuth Tests Complete ===\n")
    print("Summary:")
    print(f"- Google GCS OAuth: HTTP {results.get('gcs', 0)}")
    print(f"- Google Secret Manager OAuth: HTTP {results.get('secret_manager', 0)}")
    print()
    
    if all(code == 200 for code in results.values()):
        print("✅ All OAuth tests PASSED")
    else:
        print("⚠️  Some tests did not return HTTP 200")
        print("This may be expected if credentials are not configured")

if __name__ == '__main__':
    main()
