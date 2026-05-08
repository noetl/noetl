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


# ---------------------------------------------------------------------------
# render.args carve-out — mirrors the error.diagnosis tests above. The widget
# render contract (`{type: "app:<kind>", args: {...}}`) carries the
# chatui-aligned widget tree. Without an explicit allow-path, the projection
# strips render.args and only `render.type` survives — see
# bridge/outbox/20260508-064720-deploy-widget-renderer-round-2-local.result.json
# (executions 622377612446270148 and 622377613679395529).
# ---------------------------------------------------------------------------


def test_render_args_nested_dict_survives_projection():
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "render": {
                "type": "app:column",
                "args": {
                    "children": [
                        {
                            "type": "app:alert",
                            "args": {"message": "widget renderer is live", "variant": "success"},
                        },
                        {
                            "type": "app:markdown",
                            "args": {"text": "## Widget smoke\n\n* alert above"},
                        },
                        {
                            "type": "app:button",
                            "args": {
                                "text": "reopen execution",
                                "variant": "primary",
                                "event": {"key": "command", "value": "report 1234"},
                            },
                        },
                    ]
                },
            }
        }
    )

    assert projected["render"]["type"] == "app:column"
    children = projected["render"]["args"]["children"]
    assert [child["type"] for child in children] == [
        "app:alert",
        "app:markdown",
        "app:button",
    ]
    assert children[0]["args"] == {
        "message": "widget renderer is live",
        "variant": "success",
    }
    assert children[1]["args"] == {"text": "## Widget smoke\n\n* alert above"}
    assert children[2]["args"]["event"] == {"key": "command", "value": "report 1234"}


def test_render_args_unknown_type_still_survives_projection():
    """Mirrors the 'unsupported widget' fallback smoke — args must reach the GUI
    even when the GUI doesn't recognize the widget type, so the renderer can
    show the JSON preview to the playbook author."""
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "render": {
                "type": "app:nonexistent",
                "args": {"hello": "world", "nested": {"deeper": True}},
            }
        }
    )

    assert projected["render"]["type"] == "app:nonexistent"
    assert projected["render"]["args"] == {
        "hello": "world",
        "nested": {"deeper": True},
    }


def test_render_args_recursive_projection_has_depth_guard():
    worker = _worker()
    nested = {"leaf": "ok"}
    for idx in range(10):
        nested = {f"level_{idx}": nested}

    projected = worker._extract_control_context(
        {
            "render": {
                "type": "app:column",
                "args": {"children": [nested]},
            }
        }
    )

    # Depth guard mirrors error.diagnosis: max_depth=8 in
    # _preserve_recursive_control_value. The projection should not crash on
    # over-deep payloads — it just stops recursing past the cap.
    assert projected["render"]["type"] == "app:column"
    assert "args" in projected["render"]


def test_render_with_only_type_no_args_still_projects():
    """Defensive: if a playbook emits {type: ...} with no args, the projection
    should still surface the type so the GUI's 'unsupported widget' fallback can
    render and the playbook author sees what they emitted."""
    worker = _worker()
    projected = worker._extract_control_context(
        {"render": {"type": "app:horizontalline"}}
    )

    assert projected["render"]["type"] == "app:horizontalline"
    # No args carve-out triggered, but the scalar `type` survives.
    assert "args" not in projected["render"]


def test_render_args_top_level_list_survives_projection():
    """Some widgets accept array-shaped args (e.g. infogrid.widgets), but the
    canonical contract is `args: { ... }`. Defensively support a list-typed
    `args` so a future widget kind that takes a top-level list isn't stripped."""
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "render": {
                "type": "app:custom_list_widget",
                "args": [
                    {"type": "app:alert", "args": {"message": "first", "variant": "info"}},
                    {"type": "app:alert", "args": {"message": "second", "variant": "warning"}},
                ],
            }
        }
    )

    assert projected["render"]["type"] == "app:custom_list_widget"
    assert isinstance(projected["render"]["args"], list)
    assert len(projected["render"]["args"]) == 2
    assert projected["render"]["args"][0]["args"]["message"] == "first"
