from noetl.worker.nats_worker import Worker
from noetl.worker.result_handler import _compact_control_data


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


def test_noetl_agent_data_survives_projection():
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "status": "ok",
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/amadeus",
            "data": {
                "status": "ok",
                "isError": False,
                "data": {
                    "ok": True,
                    "items": [{"name": "hydrated activity"}],
                    "items_total": 1,
                },
            },
        }
    )

    assert projected["framework"] == "noetl"
    assert projected["data"]["data"]["ok"] is True
    assert projected["data"]["data"]["items"] == [{"name": "hydrated activity"}]


def test_control_data_survives_projection_for_large_mcp_results():
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "status": "ok",
            "control_data": {
                "ok": True,
                "items": [{"name": "bounded activity"}],
                "activities_total": 1799,
            },
        }
    )

    assert projected["status"] == "ok"
    assert projected["control_data"]["ok"] is True
    assert projected["control_data"]["items"] == [{"name": "bounded activity"}]
    assert projected["control_data"]["activities_total"] == 1799


def test_large_mcp_result_compacts_control_data_to_items():
    compact = _compact_control_data(
        {
            "status": "ok",
            "isError": False,
            "_meta": {"tool": "search_activities"},
            "data": {
                "ok": True,
                "status_code": 200,
                "activities": [{"id": idx} for idx in range(20)],
            },
        }
    )

    assert compact["ok"] is True
    assert compact["status_code"] == 200
    assert compact["isError"] is False
    assert compact["_meta"] == {"tool": "search_activities"}
    assert compact["activities_total"] == 20
    assert compact["items"] == [{"id": idx} for idx in range(10)]
    assert "activities" not in compact


def test_non_agent_data_stays_out_of_projection():
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "status": "ok",
            "data": {"ok": True, "items": [{"name": "too broad"}]},
        }
    )

    assert projected == {"status": "ok"}


def test_meta_inline_decision_survives_projection():
    """The NoETL agent bridge attaches `meta.inline_decision` (a dict
    carrying inline / reasons / depth / mode) to the agent envelope when
    NOETL_INLINE_TRIVIAL_CHILDREN=dry_run. Without an explicit carve-out
    in `_extract_control_context` the dict-of-dict gets stripped by the
    nested-scalars-only rule and the decision never reaches the event
    log's result.context.meta. Same pattern as the error.diagnosis and
    render.args carve-outs above.

    Regression for the visibility gap observed when first enabling the
    dry-run flag on the live GKE cluster: the detector was firing (per
    worker logs) but `meta.inline_decision` was missing from every
    /api/executions/{id}/events row.
    """
    worker = _worker()
    decision = {
        "inline": False,
        "reasons": [
            "framework:ok:noetl",
            "metadata:skip:inline_when_safe_not_true",
            "allow_list:ok:path_matched",
            "steps:ok:1<=3",
            "callback:ok:none",
        ],
        "depth": 0,
        "mode": "allow_list",
    }
    projected = worker._extract_control_context(
        {
            "status": "ok",
            "framework": "noetl",
            "entrypoint": "automation/agents/mcp/firestore",
            "data": {"ok": True, "value": 1},
            "execution_id": "63504...",
            "duration": 0.21,
            "meta": {"inline_decision": decision},
        }
    )

    # Sanity: the scalar fields still survive (existing behavior).
    assert projected["status"] == "ok"
    assert projected["framework"] == "noetl"
    assert projected["entrypoint"] == "automation/agents/mcp/firestore"
    assert projected["execution_id"] == "63504..."
    assert projected["duration"] == 0.21
    # The agent's data carve-out still kicks in (framework: noetl).
    assert projected["data"]["ok"] is True

    # The new behavior — meta.inline_decision is preserved.
    assert "meta" in projected, "meta key should be preserved for inline_decision"
    assert "inline_decision" in projected["meta"]
    persisted = projected["meta"]["inline_decision"]
    assert persisted["inline"] is False
    assert persisted["depth"] == 0
    assert persisted["mode"] == "allow_list"
    # Reasons list (scalar strings) round-trips through
    # _preserve_recursive_control_value.
    assert "framework:ok:noetl" in persisted["reasons"]


def test_meta_without_inline_decision_does_not_synthesize_meta_key():
    """The carve-out only fires when meta.inline_decision is present.
    A generic meta dict with only-non-scalar children still gets the
    nested-scalars-only treatment and contributes nothing — proving the
    fix is targeted, not a wholesale relaxation of the projection rule.
    """
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "status": "ok",
            # meta carries no inline_decision and no scalar children:
            # the existing rule should produce nothing for the meta key.
            "meta": {"unrelated_dict": {"nested": "value"}},
        }
    )

    assert projected["status"] == "ok"
    assert "meta" not in projected


def test_widget_envelope_payload_survives_projection():
    """The travel itinerary-planner playbook emits widget envelopes shaped
    as ``{schema_version: 1, widget_type: <str>, variant: <str>, payload:
    <dict>}`` and the SPA's WidgetRenderer requires the nested ``payload``
    dict (it dispatches on ``isWidgetEnvelope`` which checks
    ``isRecord(value.payload)``).  Without the widget-envelope carve-out,
    the universal ``payload`` entry in ``blocked_keys`` and the
    nested-scalars-only filter together strip the render config and the
    chat falls back to plain-text output.  Regression for the muno
    ``date_range_picker`` symptom — see ai-meta
    ``handoffs/archive/2026-05-27-itinerary-planner-empty-widget/``.
    """
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "bot_message": "Pick the travel dates.",
            "first_widget": {
                "schema_version": 1,
                "widget_type": "date_range_picker",
                "variant": "compact",
                "payload": {
                    "min_date": "2026-05-27",
                    "max_date": "2027-05-27",
                    "default_from": "2026-06-17",
                    "default_to": "2026-06-21",
                    "locale": "en",
                    "submit": "submit",
                },
            },
        }
    )

    first = projected["first_widget"]
    assert first["schema_version"] == 1
    assert first["widget_type"] == "date_range_picker"
    assert first["variant"] == "compact"
    payload = first["payload"]
    assert payload["min_date"] == "2026-05-27"
    assert payload["max_date"] == "2027-05-27"
    assert payload["default_from"] == "2026-06-17"
    assert payload["default_to"] == "2026-06-21"
    assert payload["locale"] == "en"
    assert payload["submit"] == "submit"


def test_widget_envelope_carve_out_only_fires_for_envelope_shape():
    """The carve-out is structurally targeted — only triggers when the
    child carries ``schema_version == 1`` AND a str ``widget_type`` AND a
    dict ``payload``.  Unrelated dicts that happen to have a ``payload``
    key keep being stripped (the universal data-plane block stands).
    """
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "looks_like_widget_but_isnt": {
                # No schema_version + no widget_type → not a widget envelope.
                "payload": {"nested": "value"},
                "label": "scalar-keeps",
            },
        }
    )

    assert projected["looks_like_widget_but_isnt"] == {"label": "scalar-keeps"}


def test_widget_envelope_carve_out_preserves_nested_lists_in_payload():
    """``payload`` dicts can carry nested lists (e.g. flight_list items,
    place autocomplete suggestions).  The recursive preserve helper must
    round-trip them.
    """
    worker = _worker()
    projected = worker._extract_control_context(
        {
            "first_widget": {
                "schema_version": 1,
                "widget_type": "place_autocomplete_input",
                "variant": "default",
                "payload": {
                    "placeholder": "Where do you want to go?",
                    "suggestions": [
                        {"label": "Miami", "id": "MIA", "kind": "city"},
                        {"label": "Paris", "id": "PAR", "kind": "city"},
                    ],
                    "submit_on_select": True,
                },
            },
        }
    )

    payload = projected["first_widget"]["payload"]
    assert payload["placeholder"] == "Where do you want to go?"
    assert payload["suggestions"] == [
        {"label": "Miami", "id": "MIA", "kind": "city"},
        {"label": "Paris", "id": "PAR", "kind": "city"},
    ]
    assert payload["submit_on_select"] is True
