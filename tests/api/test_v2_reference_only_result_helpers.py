import noetl.server.api.v2 as v2_api


def test_build_reference_only_result_supports_result_kind_ref():
    result = v2_api._build_reference_only_result(
        payload={},
        status="RUNNING",
        result_kind="ref",
        result_uri="gs://bucket/key.json",
    )

    assert result == {
        "status": "RUNNING",
        "reference": {"type": "object_store", "url": "gs://bucket/key.json"},
    }


def test_build_reference_only_result_supports_result_kind_refs():
    result = v2_api._build_reference_only_result(
        payload={},
        status="COMPLETED",
        result_kind="refs",
        event_ids=[101, "bad", 202],
    )

    assert result == {
        "status": "COMPLETED",
        "reference": {"type": "event_refs", "event_ids": [101, 202]},
    }


def test_extract_reference_from_worker_ref_wrapper():
    payload = {
        "response": {
            "_ref": {
                "ref": "public.table:42",
                "store": "postgres",
                "meta": {
                    "bytes": 512,
                    "sha256": "abc",
                    "content_type": "application/json",
                    "compression": "gzip",
                },
            }
        }
    }
    result = v2_api._build_reference_only_result(payload=payload, status="COMPLETED")

    assert result["status"] == "COMPLETED"
    assert result["reference"] == {
        "type": "relational",
        "record_id": "public.table:42",
        "bytes": 512,
        "sha256": "abc",
        "content_type": "application/json",
        "compression": "gzip",
    }


def test_extract_context_filters_transport_wrappers_and_honors_size_limit(monkeypatch):
    monkeypatch.setattr(v2_api, "_EVENT_RESULT_CONTEXT_MAX_BYTES", 64)

    context = v2_api._extract_context_from_payload(
        {
            "context": {
                "_ref": {"ref": "x"},
                "_preview": {"x": 1},
                "preview": {"y": 2},
                "extracted": {"z": 3},
                "safe": "x" * 200,
            }
        }
    )
    assert context is None

    context = v2_api._extract_context_from_payload(
        {
            "context": {
                "_ref": {"ref": "x"},
                "_preview": {"x": 1},
                "safe": "ok",
                "command_id": "cmd-1",
            }
        }
    )
    assert context == {"safe": "ok", "command_id": "cmd-1"}


def test_build_reference_only_result_outputs_contract_shape():
    payload = {
        "reference": {"type": "nats", "locator": "nats://bucket/key"},
        "context": {"command_id": "cmd-1", "status": "inner"},
        "response": {"data": {"large": "ignored"}},
        "random": {"will_not": "appear"},
    }
    result = v2_api._build_reference_only_result(payload=payload, status="FAILED")

    assert set(result.keys()).issubset({"status", "reference", "context"})
    assert isinstance(result["status"], str)
    assert isinstance(result.get("reference"), dict)
    assert isinstance(result.get("context"), dict)
