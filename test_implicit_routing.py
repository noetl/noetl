#!/usr/bin/env python3
import requests
import time

# Register
with open('test_implicit_end_routing.yaml') as f:
    content = f.read()

resp = requests.post(
    'http://localhost:8082/api/catalog/register',
    json={'content': content, 'resource_type': 'Playbook'}
)
print(f'Register: {resp.status_code}')
reg_result = resp.json()
catalog_id = reg_result.get('catalog_id')
print(f'Catalog ID: {catalog_id}, Version: {reg_result.get("version")}')

# Execute
resp = requests.post(
    'http://localhost:8082/api/run/playbook',
    json={'catalog_id': catalog_id}
)
print(f'Execute: {resp.status_code}')
result = resp.json()
execution_id = result.get('execution_id')
print(f'Execution ID: {execution_id}')

if not execution_id:
    print('ERROR:', result)
    exit(1)

# Wait
print('Waiting 10 seconds...')
time.sleep(10)

# Check events
events_resp = requests.get(f'http://localhost:8082/api/events?execution_id={execution_id}')
events = events_resp.json()

print(f'\nTotal events: {len(events)}')
print('\nEvent flow:')
for e in events:
    print(f"  {e.get('event_type'):25s} node: {e.get('node_name'):15s} status: {e.get('status')}")

# Check if step1 routed to end
step1_completed = [e for e in events if e.get('node_name') == 'step1' and e.get('event_type') == 'step_completed']
end_started = [e for e in events if e.get('node_name') == 'end' and e.get('event_type') == 'step_started']
end_exit = [e for e in events if e.get('node_name') == 'end' and e.get('event_type') == 'step.exit']

print(f"\nstep1 completed: {len(step1_completed)}")
print(f"end started: {len(end_started)}")
print(f"end exit: {len(end_exit)}")

if end_started:
    print('\n✓ SUCCESS: step1 implicitly routed to end!')
else:
    print('\n✗ FAILED: step1 did NOT route to end')
