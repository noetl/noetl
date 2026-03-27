import pytest

import noetl.server.api.v2 as v2_api


def test_build_reference_only_result_uses_strict_result_envelope():
    payload = {
        "result": {
            "status": "completed",
            "reference": {"type": "relational", "schema": "public", "table": "x", "record_id": "42"},
            "context": {"facility_mapping_id": 46, "command_id": "cmd-1"},
        },
        "command_id": "cmd-1",
    }

    result = v2_api._build_reference_only_result(payload=payload, status="RUNNING")

    assert result["status"] == "COMPLETED"
    assert result["reference"]["type"] == "relational"
    assert result["context"]["facility_mapping_id"] == 46
    assert result["context"]["command_id"] == "cmd-1"


def test_build_reference_only_result_does_not_derive_from_response_payload():
    payload = {
        "response": {"rows": [{"id": 1}]},
        "result": {"status": "completed"},
    }
    result = v2_api._build_reference_only_result(payload=payload, status="COMPLETED")
    assert result == {"status": "COMPLETED"}


def test_build_reference_only_result_keeps_compact_top_level_context_fields():
    payload = {
        "result": {"status": "RUNNING"},
        "request_id": "req-1",
        "event_ids": [10, 11],
        "commands_generated": 3,
    }
    result = v2_api._build_reference_only_result(payload=payload, status="RUNNING")
    assert result["context"]["request_id"] == "req-1"
    assert result["context"]["event_ids"] == [10, 11]
    assert result["context"]["commands_generated"] == 3


def test_build_reference_only_result_normalizes_status_aliases():
    success_payload = {"result": {"status": "success"}}
    failed_payload = {"result": {"status": "error"}}

    success_result = v2_api._build_reference_only_result(payload=success_payload, status="running")
    failed_result = v2_api._build_reference_only_result(payload=failed_payload, status="running")

    assert success_result["status"] == "COMPLETED"
    assert failed_result["status"] == "FAILED"


def test_validate_reference_only_payload_rejects_legacy_response_key():
    with pytest.raises(ValueError, match="forbidden inline output keys"):
        v2_api._validate_reference_only_payload(
            {"response": {"rows": [{"id": 1}]}}
        )


def test_validate_reference_only_payload_rejects_legacy_command_keys_in_context():
    with pytest.raises(ValueError, match="legacy command_\\* keys"):
        v2_api._validate_reference_only_payload(
            {
                "result": {
                    "status": "completed",
                    "context": {"command_0": {"status": "success", "row_count": 1}},
                }
            }
        )


def test_validate_reference_only_payload_accepts_compact_context():
    v2_api._validate_reference_only_payload(
        {
            "result": {
                "status": "completed",
                "context": {"facility_mapping_id": 46, "command_id": "x-1"},
            }
        }
    )
