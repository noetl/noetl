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


def test_extract_context_derives_from_response_payload():
    context = v2_api._extract_context_from_payload(
        {
            "command_id": "cmd-42",
            "response": {
                "status": "success",
                "data": {
                    "command_0": {
                        "status": "success",
                        "row_count": 2,
                        "rows": [{"facility_mapping_id": 123}, {"facility_mapping_id": 456}],
                    }
                },
            },
        }
    )

    assert context is not None
    assert context["command_id"] == "cmd-42"
    assert "command_0" in context
    assert context["command_0"]["row_count"] == 2
    assert context["command_0"]["rows"][0]["facility_mapping_id"] == 123


def test_extract_context_compacts_large_response_payload(monkeypatch):
    monkeypatch.setattr(v2_api, "_EVENT_RESULT_CONTEXT_MAX_BYTES", 768)
    monkeypatch.setattr(v2_api, "_EVENT_RESULT_CONTEXT_MAX_ROWS_PER_COMMAND", 1)

    context = v2_api._extract_context_from_payload(
        {
            "command_id": "cmd-99",
            "response": {
                "status": "success",
                "data": {
                    "command_0": {
                        "status": "success",
                        "row_count": 2000,
                        "rows": [{"id": i, "value": "x" * 32} for i in range(20)],
                    }
                },
            },
        }
    )

    assert context is not None
    assert context["command_id"] == "cmd-99"
    assert context["command_0"]["row_count"] == 2000
    assert len(context["command_0"]["rows"]) == 1
    assert context["command_0"]["rows"][0]["id"] == 0


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
