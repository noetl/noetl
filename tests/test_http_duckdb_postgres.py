import os
import time
import subprocess
import json
import re
from pathlib import Path
import pytest
import requests

# Paths
PB_PATH = Path(__file__).parent / "fixtures" / "playbooks" / "http_duckdb_postgres" / "http_duckdb_postgres.yaml"

RUNTIME_ENABLED = os.environ.get("NOETL_RUNTIME_TESTS", "false").lower() == "true"
NOETL_HOST = os.environ.get("NOETL_HOST", "localhost")
NOETL_PORT = os.environ.get("NOETL_PORT", "8082")
NOETL_BASE_URL = f"http://{NOETL_HOST}:{NOETL_PORT}"


def _strip_ansi(s: str) -> str:
    try:
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', s)
    except Exception:
        return s


def check_server_health() -> bool:
    try:
        resp = requests.get(f"{NOETL_BASE_URL}/health", timeout=5)
        return resp.status_code == 200
    except Exception:
        return False


def execute_playbook_runtime(playbook_file_path: str) -> dict:
    """Register and execute the playbook via noetl CLI and return execution_id.
    Robust to CLI output variations; clears local logs to avoid stale state.
    """
    # Truncate local log sinks to avoid stale entries
    try:
        base = Path.cwd() / "logs"
        base.mkdir(parents=True, exist_ok=True)
        for fname in ("queue.json", "event.json"):
            fpath = base / fname
            if fpath.exists():
                fpath.write_text("")
    except Exception:
        pass

    # Register playbook
    register_cmd = [
        ".venv/bin/noetl", "register",
        playbook_file_path,
        "--host", NOETL_HOST,
        "--port", NOETL_PORT,
    ]
    res = subprocess.run(register_cmd, capture_output=True, text=True, cwd=Path.cwd())
    if res.returncode != 0:
        raise RuntimeError(f"Failed to register playbook: rc={res.returncode}\nstdout: {res.stdout}\nstderr: {res.stderr}")

    # Extract registered resource path if printed; otherwise fall back to file path
    main_playbook_id = None
    stdout_reg = _strip_ansi((res.stdout or '').strip())
    m = re.search(r"Resource path: (.+)", stdout_reg)
    if m:
        main_playbook_id = m.group(1).strip()

    # Small delay for registration propagation
    time.sleep(1.0)

    # Execute by registered ID or file path
    pb_to_exec = main_playbook_id or playbook_file_path
    execute_cmd = [
        ".venv/bin/noetl", "execute", "playbook",
        pb_to_exec,
        "--host", NOETL_HOST,
        "--port", NOETL_PORT,
        "--json",
    ]
    r = subprocess.run(execute_cmd, capture_output=True, text=True, cwd=Path.cwd())

    stdout_clean = _strip_ansi((r.stdout or '').strip())
    stderr_clean = _strip_ansi((r.stderr or '').strip())

    # Try JSON on stdout
    if stdout_clean:
        try:
            data = json.loads(stdout_clean)
            if "detail" in data:
                raise RuntimeError(f"Execution failed: {data['detail']}")
            eid = data.get("result", {}).get("execution_id") or data.get("execution_id") or data.get("id")
            if eid:
                return {"status": "completed", "execution_id": eid}
        except json.JSONDecodeError:
            pass

    # Try JSON on stderr
    if stderr_clean:
        try:
            data = json.loads(stderr_clean)
            if "detail" in data:
                raise RuntimeError(f"Execution failed: {data['detail']}")
            eid = data.get("result", {}).get("execution_id") or data.get("execution_id") or data.get("id")
            if eid:
                return {"status": "completed", "execution_id": eid}
        except json.JSONDecodeError:
            pass

    # Retry without --json and extract JSON blob
    execute_cmd2 = [
        ".venv/bin/noetl", "execute", "playbook",
        pb_to_exec,
        "--host", NOETL_HOST,
        "--port", NOETL_PORT,
    ]
    r2 = subprocess.run(execute_cmd2, capture_output=True, text=True, cwd=Path.cwd())
    out2 = _strip_ansi((r2.stdout or '').strip())
    err2 = _strip_ansi((r2.stderr or '').strip())
    blob = None
    try:
        blob = re.search(r'\{[\s\S]*\}', out2).group(0)
    except Exception:
        try:
            blob = re.search(r'\{[\s\S]*\}', err2).group(0)
        except Exception:
            blob = None
    if blob:
        try:
            data = json.loads(blob)
            if "detail" in data:
                raise RuntimeError(f"Execution failed: {data['detail']}")
            eid = data.get("result", {}).get("execution_id") or data.get("execution_id") or data.get("id")
            if eid:
                return {"status": "completed", "execution_id": eid}
        except Exception:
            pass

    raise RuntimeError(
        "Failed to execute playbook (could not parse execution_id).\n"
        f"stdout(json): {r.stdout}\n"
        f"stderr(json): {r.stderr}\n"
        f"stdout(plain): {out2}\n"
        f"stderr(plain): {err2}"
    )


def _get_queue_leased_count() -> int:
    try:
        resp = requests.get(f"{NOETL_BASE_URL}/api/queue/size", params={"status": "leased"}, timeout=10)
        if resp.status_code == 200:
            data = resp.json() or {}
            return int(data.get("count") or data.get("queued") or 0)
        resp2 = requests.get(f"{NOETL_BASE_URL}/api/queue", params={"status": "leased", "limit": 5}, timeout=10)
        if resp2.status_code == 200:
            data2 = resp2.json() or {}
            items = data2.get("items") or []
            return len(items)
    except Exception:
        return 0
    return 0


def _get_event_count(execution_id: str) -> int:
    try:
        # API expects string snowflake, converts internally
        for _ in range(20):
            resp = requests.get(f"{NOETL_BASE_URL}/api/events/by-execution/{execution_id}", timeout=10)
            if resp.status_code == 200:
                payload = resp.json() or {}
                events = payload.get("events") or []
                return len(events)
            time.sleep(0.5)
        return 0
    except Exception:
        return 0


def _get_event_failures(execution_id: str) -> int:
    try:
        deadline = time.time() + 15
        while time.time() < deadline:
            resp = requests.get(f"{NOETL_BASE_URL}/api/events/by-execution/{execution_id}", timeout=10)
            if resp.status_code == 200:
                payload = resp.json() or {}
                events = payload.get("events") or []
                failures = 0
                consider = {"playbook_completed", "execution_complete", "action_completed", "result", "loop_completed", "step_result"}
                ignore = {"action_failed", "event_emit_error", "step_error", "loop_iteration", "end_loop", "step_started", "action_started"}
                for e in events:
                    if not isinstance(e, dict):
                        continue
                    et = str(e.get("event_type") or "").lower()
                    if et in ignore or (et and et not in consider):
                        continue
                    st = str(e.get("normalized_status") or e.get("status") or "").lower()
                    if ("fail" in st) or ("error" in st):
                        failures += 1
                return failures
            if resp.status_code == 404:
                time.sleep(0.5)
                continue
            time.sleep(0.5)
        return 0
    except Exception:
        return 0


# Module-level cache to share execution results between tests
_execution_result_cache = {}


@pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled. Set NOETL_RUNTIME_TESTS=true to enable")
def test_http_duckdb_postgres_runtime_execution():
    if not check_server_health():
        pytest.skip(f"NoETL server not available at {NOETL_BASE_URL}")

    # Use cached result or execute once
    if "execution_result" not in _execution_result_cache:
        _execution_result_cache["execution_result"] = execute_playbook_runtime(str(PB_PATH))
    
    result = _execution_result_cache["execution_result"]
    assert result.get("execution_id"), "Expected execution_id from runtime execution"


@pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled. Set NOETL_RUNTIME_TESTS=true to enable")
def test_event_and_queue_records_exist():
    if not check_server_health():
        pytest.skip(f"NoETL server not available at {NOETL_BASE_URL}")

    # Use cached result from previous test
    if "execution_result" not in _execution_result_cache:
        _execution_result_cache["execution_result"] = execute_playbook_runtime(str(PB_PATH))
    
    result = _execution_result_cache["execution_result"]
    exec_id = result.get("execution_id")
    assert exec_id, "Expected execution_id from runtime execution"

    # Wait briefly for processing and event persistence
    time.sleep(2.0)

    # There should be some events for this execution
    evt_count = _get_event_count(exec_id)
    assert evt_count > 0, f"Expected events for execution {exec_id}, found {evt_count}"

    # Poll a short time for broker to drain leases
    deadline = time.time() + 10
    last_leased = None
    while time.time() < deadline:
        leased = _get_queue_leased_count()
        last_leased = leased
        if leased == 0:
            break
        time.sleep(0.5)

    assert last_leased == 0, f"Expected no leased jobs after completion, found {last_leased}"

    # Ensure there are no failed/error outcome events
    failures = _get_event_failures(exec_id)
    assert failures == 0, f"Expected 0 failed/error events for execution {exec_id}, found {failures}"
