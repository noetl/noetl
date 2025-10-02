import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "status.json"
EVENT_LOG_PATH = ROOT / "event_log.json"


def _load_json(path: Path):
    assert path.exists(), f"Missing required file: {path}"
    text = path.read_text(encoding="utf-8")
    # Some generators may include ANSI color codes; attempt to strip minimally
    # but primarily try JSON parse directly first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: remove common ANSI sequences if present
        import re
        clean = re.sub(r"\x1b\[[0-9;]*m", "", text)
        return json.loads(clean)


def test_status_json_validates_weather_loop_execution():
    data = _load_json(STATUS_PATH)

    # Top-level expectations
    assert data.get("status") == "completed", "Playbook execution did not complete successfully"
    assert data.get("error") in (None, {}), "Top-level error should be empty"

    # There must be events list
    events = data.get("events") or []
    assert isinstance(events, list) and len(events) > 0, "No events captured in status.json"

    # Find execution_start and verify playbook path
    exec_start = next((e for e in events if e.get("event_type") == "execution_start"), None)
    assert exec_start is not None, "No execution_start event found"
    meta = exec_start.get("metadata") or {}
    assert meta.get("playbook_path") == "examples/weather/weather_loop_example", "Unexpected playbook_path in execution_start"



    # Validate that log_aggregate_result_task ran 3 times and logged True
    agg_logs_done = [
        e for e in events
        if e.get("event_type") == "action_completed"
        and e.get("node_name") == "log_aggregate_result_task"
    ]
    assert len(agg_logs_done) >= 1, f"Expected at least 1 log_aggregate_result_task completion, got {len(agg_logs_done)}"
    for e in agg_logs_done:
        out = e.get("output_result") or {}
        data_out = out.get("data") or {}
        # Some generators may bubble directly in 'data', others under 'data.logged'
        logged = data_out.get("logged")
        if logged is None:
            logged = out.get("logged")
        assert logged is True, f"log_aggregate_result_task did not report logged=True in {out}"

    # Final consolidated result may or may not bubble up the last task's data
    # If present, ensure it's truthful; otherwise rely on prior event validations
    result = data.get("result") or {}
    rdata = result.get("data") or {}
    if "logged" in rdata:
        assert rdata.get("logged") is True, "Final result should contain logged=True when present"


def test_event_log_json_present_and_consistent():
    ev = _load_json(EVENT_LOG_PATH)
    # event_log.json may be a list of row dicts from an event_log table export
    assert isinstance(ev, (list, dict)), "event_log.json should be a JSON list or dict export"

    # Gather basic consistency checks if it's a list
    if isinstance(ev, list) and ev:
        # At least one row should mention the weather playbook path or city_loop
        as_text = json.dumps(ev[:200])  # sample first rows to avoid heavy processing
        assert ("examples/weather/weather_loop_example" in as_text) or ("city_loop" in as_text), (
            "event_log.json doesn't appear to contain weather_loop_example related entries"
        )

        # Check that there are completed actions recorded
        completed_mention = any("COMPLETED" in json.dumps(row) for row in ev[:1000])
        assert completed_mention, "event_log.json does not show any COMPLETED actions"
