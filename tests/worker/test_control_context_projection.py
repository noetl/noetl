from noetl.worker.nats_worker import Worker


def _worker() -> Worker:
    return Worker.__new__(Worker)


def test_error_diagnosis_diagnosis_fetch_meta_survives_projection():
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "error": {
                "kind": "subflow_failed",
                "message": "subflow failed",
                "diagnosis": {
                    "category": "bad_request",
                    "confidence": 0.95,
                    "root_cause": "bad payload",
                    "suggested_action": "fix the payload",
                    "source": "vertex-ai",
                    "_meta": {
                        "diagnosis_fetch": {
                            "poll_count": 3,
                            "elapsed_seconds": 1.42,
                            "deadline_seconds": 60.0,
                            "hit_deadline": False,
                        }
                    },
                },
            }
        }
    )

    diagnosis_fetch = projected["error"]["diagnosis"]["_meta"]["diagnosis_fetch"]
    assert diagnosis_fetch == {
        "poll_count": 3,
        "elapsed_seconds": 1.42,
        "deadline_seconds": 60.0,
        "hit_deadline": False,
    }


def test_error_diagnosis_arbitrary_nested_dict_survives_projection():
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "error": {
                "kind": "subflow_failed",
                "diagnosis": {
                    "category": "infra",
                    "confidence": 0.8,
                    "root_cause": "synthetic",
                    "suggested_action": "inspect",
                    "source": "vertex-ai",
                    "custom_field": {
                        "nested": {
                            "deeper": {
                                "a": 1,
                                "b": 2,
                            }
                        }
                    },
                },
            }
        }
    )

    assert projected["error"]["diagnosis"]["custom_field"]["nested"]["deeper"] == {
        "a": 1,
        "b": 2,
    }


def test_error_diagnosis_recursive_projection_has_depth_guard():
    worker = _worker()
    nested = {"leaf": "ok"}
    for idx in range(10):
        nested = {f"level_{idx}": nested}

    projected = worker._extract_control_context(
        {
            "error": {
                "kind": "subflow_failed",
                "diagnosis": {
                    "category": "infra",
                    "confidence": 0.8,
                    "root_cause": "synthetic",
                    "suggested_action": "inspect",
                    "source": "vertex-ai",
                    "deep": nested,
                },
            }
        }
    )

    assert projected["error"]["diagnosis"]["deep"] == nested


def test_error_diagnosis_scalar_root_fields_still_survive_projection():
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "error": {
                "kind": "subflow_failed",
                "message": "subflow failed",
                "diagnosis": {
                    "category": "bad_request",
                    "confidence": 0.95,
                    "root_cause": "bad payload",
                    "suggested_action": "fix the payload",
                    "source": "vertex-ai",
                    "model": "gemini-2.5-flash",
                    "escalated": False,
                },
            }
        }
    )

    assert projected["error"]["kind"] == "subflow_failed"
    assert projected["error"]["message"] == "subflow failed"
    assert projected["error"]["diagnosis"] == {
        "category": "bad_request",
        "confidence": 0.95,
        "root_cause": "bad payload",
        "suggested_action": "fix the payload",
        "source": "vertex-ai",
        "model": "gemini-2.5-flash",
        "escalated": False,
    }
