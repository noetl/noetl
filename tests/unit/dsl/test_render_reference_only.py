import pytest

from noetl.core.dsl.render import TaskResultProxy


def test_task_result_proxy_exposes_canonical_data_and_rejects_result_alias():
    proxy = TaskResultProxy({"rows": [{"id": 1}], "status": "success"})

    assert proxy.data.rows[0]["id"] == 1
    assert proxy.data.status == "success"
    with pytest.raises(AttributeError):
        _ = proxy.result


def test_task_result_proxy_falls_back_to_context_for_attribute_access():
    # ``ExecutionState.to_dict()`` compacts persisted step_results by
    # stripping top-level dict-valued fields and keeping the producer's
    # full output only under ``context`` (the alias added by
    # ``mark_step_completed``).  The proxy must therefore resolve
    # ``step.field`` against ``data["context"][field]`` when the field
    # is no longer at the top level after a state reload.  Without
    # this fallback, ``{{ normalize_input.input_event }}`` (and any
    # other dict-valued producer field) silently renders to
    # ``Undefined`` on the second and subsequent template renders
    # within an execution.
    proxy = TaskResultProxy(
        {
            "status": "COMPLETED",
            "context": {"facility_mapping_id": 46},
        }
    )

    assert proxy.facility_mapping_id == 46
    assert proxy.context.facility_mapping_id == 46


def test_task_result_proxy_context_fallback_prefers_top_level():
    # Top-level lookup wins over ``context.<name>`` when both exist.
    # This guards against a producer that intentionally puts a
    # different value at the top level than under ``context``.
    proxy = TaskResultProxy(
        {
            "status": "COMPLETED",
            "thread_path": "top-level-path",
            "context": {"thread_path": "context-path"},
        }
    )

    assert proxy.thread_path == "top-level-path"


def test_task_result_proxy_compacted_step_result_resolves_dict_field():
    # Regression: the muno itinerary-planner playbook's ``normalize_input``
    # step writes ``input_event: {...}`` at the top level.  The
    # ``mark_step_completed`` writer aliases the full dict under
    # ``context``; the compaction layer then strips the top-level
    # ``input_event`` dict on the next state persist.  After the
    # reload, the proxy still has to make
    # ``{{ normalize_input.input_event }}`` resolve.
    compacted_normalize_input = {
        "status": "COMPLETED",
        "thread_path": "chat_threads/travel-ui-x-y",
        "thread_id": "travel-ui-x-y",
        "event_type": "user_message",
        "replay": False,
        "context": {
            "thread_path": "chat_threads/travel-ui-x-y",
            "thread_id": "travel-ui-x-y",
            "event_type": "user_message",
            "event_payload": {"text": "trip to paris"},
            "input_event": {
                "type": "user_message",
                "payload": {"text": "trip to paris"},
                "actor": {"kind": "user", "uid": "guest"},
            },
            "replay": False,
        },
    }
    proxy = TaskResultProxy(compacted_normalize_input)

    # Scalar fields surviving compaction at top level.
    assert proxy.thread_path == "chat_threads/travel-ui-x-y"
    assert proxy.event_type == "user_message"

    # Dict fields stripped by compaction, resolvable via context
    # fallback.  ``input_event`` is the field that previously rendered
    # to ``Undefined`` and broke the extract_turn LLM call.
    input_event = proxy.input_event
    assert input_event["type"] == "user_message"
    assert input_event["payload"]["text"] == "trip to paris"

    event_payload = proxy.event_payload
    assert event_payload["text"] == "trip to paris"
