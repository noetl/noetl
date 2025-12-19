#!/usr/bin/env python3
import json, time, yaml, httpx

BASE_URL = "http://localhost:8082"
yaml_path = "test_simple_loop.yaml"

# Register
with open(yaml_path, 'r') as f:
    playbook = yaml.safe_load(f)

response = httpx.post(f"{BASE_URL}/api/catalog/register", json={"content": json.dumps(playbook)}, timeout=30.0)
print(f"Registration: {response.status_code}")

# Execute
response = httpx.post(f"{BASE_URL}/api/v2/execute", json={"path": playbook['metadata']['path'], "payload": {}}, timeout=30.0)
execution_id = response.json()['execution_id']
print(f"Execution ID: {execution_id}")

# Wait and query events
time.sleep(10)
response = httpx.post(
    f"{BASE_URL}/api/postgres/execute",
    json={"query": f"SELECT event_type, node_name, status FROM noetl.event WHERE execution_id = {execution_id} ORDER BY event_id", "schema": "noetl"},
    timeout=30.0
)

events = response.json().get('result', [])
print(f"\nEvents ({len(events)}):")
for e in events:
    print(f"  {e[0]:<25} {e[1]:<20} {e[2]}")

completed = any(e[0] == 'playbook_completed' for e in events)
print(f"\n{'✅ PASSED' if completed else '❌ FAILED'}: Simple loop test")
