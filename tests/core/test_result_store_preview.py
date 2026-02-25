import json

from noetl.core.storage.result_store import TempStore


def test_create_preview_truncates_nested_large_payloads():
    store = TempStore(preview_max_bytes=1024)
    payload = {
        "status": "failed",
        "_prev": {"item_id": 75, "item_key": "Item-75"},
        "results": {
            "build_large_request": {
                "item_id": 75,
                "request_blob": "x" * 262_144,
                "request_bytes": 262_144,
            }
        },
    }

    preview = store._create_preview(payload)
    preview_json = json.dumps(preview)

    assert preview.get("results") == "{1 keys}"
    assert "request_blob" not in preview_json
    assert len(preview_json.encode("utf-8")) <= 1024


def test_create_preview_marks_truncation_when_budget_exceeded():
    store = TempStore(preview_max_bytes=120)
    payload = {f"k{i}": "v" * 100 for i in range(10)}

    preview = store._create_preview(payload)

    assert preview.get("_truncated") is True
