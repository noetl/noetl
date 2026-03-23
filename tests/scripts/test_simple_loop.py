#!/usr/bin/env python3
import json
import time

import httpx
import yaml

BASE_URL = "http://localhost:8082"
YAML_PATH = "tests/fixtures/playbooks/root_scripts/test_simple_loop.yaml"
STATUS_TIMEOUT_SECONDS = 30.0


def wait_for_completion(execution_id: str) -> dict:
    deadline = time.time() + STATUS_TIMEOUT_SECONDS
    last_status = None

    while time.time() < deadline:
        response = httpx.get(
            f"{BASE_URL}/api/executions/{execution_id}/status",
            timeout=30.0,
        )
        response.raise_for_status()
        last_status = response.json()
        if last_status.get("completed"):
            return last_status
        time.sleep(1)

    raise TimeoutError(f"Execution {execution_id} did not complete within {STATUS_TIMEOUT_SECONDS}s. Last status: {last_status}")


with open(YAML_PATH, "r", encoding="utf-8") as handle:
    playbook = yaml.safe_load(handle)

register_response = httpx.post(
    f"{BASE_URL}/api/catalog/register",
    json={"content": json.dumps(playbook)},
    timeout=30.0,
)
register_response.raise_for_status()
print(f"Registration: {register_response.status_code}")

execute_response = httpx.post(
    f"{BASE_URL}/api/execute",
    json={"path": playbook["metadata"]["path"], "payload": {}},
    timeout=30.0,
)
execute_response.raise_for_status()
execution_id = str(execute_response.json()["execution_id"])
print(f"Execution ID: {execution_id}")

status = wait_for_completion(execution_id)
print(f"Status: completed={status.get('completed')} failed={status.get('failed')} current_step={status.get('current_step')}")

events_response = httpx.get(
    f"{BASE_URL}/api/executions/{execution_id}/events",
    params={"page": 1, "page_size": 100},
    timeout=30.0,
)
events_response.raise_for_status()
events_payload = events_response.json()
events = events_payload.get("events", [])

print(f"\nEvents ({len(events)}):")
for event in reversed(events):
    print(
        f"  {event.get('event_type', '-'): <25} "
        f"{event.get('node_name', '-'): <20} "
        f"{event.get('status', '-')}"
    )

passed = bool(status.get("completed")) and not bool(status.get("failed"))
print(f"\n{'PASSED' if passed else 'FAILED'}: Simple loop test")
if not passed:
    raise SystemExit(1)
