#!/usr/bin/env python3
"""
Test weather_loop_v2 playbook specifically to verify template rendering fix.
"""
import json
import time
import yaml
import httpx

BASE_URL = "http://localhost:8082"

def test_weather_loop():
    """Test weather_loop_v2 playbook."""
    yaml_path = "tests/fixtures/playbooks/examples/weather_loop_v2.yaml"
    
    print("\n" + "=" * 70)
    print(f"TEST: weather_loop_v2")
    print("=" * 70)
    print(f"File: {yaml_path}\n")
    
    # 1. Register playbook
    with open(yaml_path, 'r') as f:
        playbook_yaml = yaml.safe_load(f)
    
    playbook_json = json.dumps(playbook_yaml)
    
    response = httpx.post(
        f"{BASE_URL}/api/catalog/register",
        json={"content": playbook_json},
        timeout=30.0
    )
    print(f"✓ Registration: {response.status_code}")
    
    # 2. Execute playbook
    catalog_path = playbook_yaml['metadata']['path']
    
    response = httpx.post(
        f"{BASE_URL}/api/v2/execute",
        json={
            "path": catalog_path,
            "payload": {}
        },
        timeout=30.0
    )
    print(f"✓ Execution: {response.status_code}")
    
    result = response.json()
    execution_id = result.get('execution_id')
    print(f"  Execution ID: {execution_id}\n")
    
    # 3. Wait for execution
    print("  Waiting for execution to complete...")
    time.sleep(15)  # Weather API is external, give it time
    
    # 4. Query events
    response = httpx.post(
        f"{BASE_URL}/api/postgres/execute",
        json={
            "query": f"""
                SELECT event_type, node_name, status, error 
                FROM noetl.event 
                WHERE execution_id = {execution_id} 
                ORDER BY event_id
            """,
            "schema": "noetl"
        },
        timeout=30.0
    )
    
    events_result = response.json()
    events_raw = events_result.get('result', [])
    
    # Convert to list of dicts if needed
    events = []
    for row in events_raw:
        if isinstance(row, list):
            # Result is array of arrays: [event_type, node_name, status, error]
            events.append({
                'event_type': row[0],
                'node_name': row[1],
                'status': row[2],
                'error': row[3] if len(row) > 3 else None
            })
        elif isinstance(row, dict):
            events.append(row)
    
    print(f"\n  Events ({len(events)}):")
    for event in events:
        event_type = event.get('event_type')
        node_name = event.get('node_name')
        status = event.get('status')
        error = event.get('error')
        
        status_icon = "✓" if status == "COMPLETED" else "→"
        print(f"    {status_icon} {event_type:<22} {node_name:<30} {status}")
        
        if error:
            print(f"       ERROR: {error}")
    
    # 5. Check for failure
    failed = any(e.get('status') == 'FAILED' for e in events)
    has_error = any(e.get('error') for e in events)
    completed = any(e.get('event_type') == 'playbook_completed' for e in events)
    
    if has_error:
        print("\n❌ FAILED: Execution had errors")
        return False
    elif failed:
        print("\n❌ FAILED: Execution failed")
        return False
    elif not completed:
        print("\n❌ FAILED: Execution did not complete")
        return False
    else:
        print("\n✅ PASSED: weather_loop_v2")
        return True

if __name__ == "__main__":
    success = test_weather_loop()
    exit(0 if success else 1)
