from noetl.core.workflow.playbook.inline_execution import (
    DEFAULT_ALLOW_LIST,
    InlineDecision,
    detect_inline_child,
    load_allow_list_from_env,
)


def _playbook(**overrides):
    doc = {
        "metadata": {"name": "child", "path": "automation/agents/mcp/firestore"},
        "workflow": [
            {
                "step": "call",
                "tool": {"kind": "python"},
            }
        ],
    }
    doc.update(overrides)
    return doc


def _reason(decision, prefix):
    return any(reason.startswith(prefix) for reason in decision.reasons)


def test_allow_list_hit_is_inline_candidate():
    decision = detect_inline_child(
        _playbook(),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is True
    assert decision.mode == "allow_list"
    assert _reason(decision, "allow_list:ok")
    assert _reason(decision, "tool:ok")


def test_metadata_opt_in_boolean_true_is_inline_candidate():
    decision = detect_inline_child(
        _playbook(metadata={"name": "child", "inline_when_safe": True}),
        child_path="custom/child",
    )

    assert decision.inline is True
    assert decision.mode == "metadata_opt_in"
    assert _reason(decision, "metadata:ok")


def test_metadata_truthy_non_bool_is_rejected():
    decision = detect_inline_child(
        _playbook(metadata={"name": "child", "inline_when_safe": "true"}),
        child_path="custom/child",
    )

    assert decision.inline is False
    assert decision.mode is None
    assert "metadata:block:inline_when_safe_must_be_boolean_true" in decision.reasons


def test_not_opted_in_or_allow_listed_blocks_inline():
    decision = detect_inline_child(_playbook(), child_path="custom/child")

    assert decision.inline is False
    assert decision.mode is None
    assert "mode:block:not_opted_in_or_allow_listed" in decision.reasons


def test_depth_limit_enforced():
    decision = detect_inline_child(
        _playbook(),
        child_path="automation/agents/mcp/firestore",
        depth=4,
    )

    assert decision.inline is False
    assert "depth:block:4>3" in decision.reasons


def test_depth_can_be_read_from_parent_context():
    decision = detect_inline_child(
        _playbook(),
        {"meta": {"inline_depth": 2}},
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is True
    assert decision.depth == 2
    assert "depth:ok:2<=3" in decision.reasons


def test_step_count_limit_enforced():
    workflow = [
        {"step": "one", "tool": {"kind": "python"}},
        {"step": "two", "tool": {"kind": "mcp"}},
        {"step": "three", "tool": {"kind": "noop"}},
        {"step": "four", "tool": {"kind": "python"}},
    ]
    decision = detect_inline_child(
        _playbook(workflow=workflow),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "steps:block:4>3" in decision.reasons


def test_missing_workflow_blocks_inline():
    decision = detect_inline_child(
        _playbook(workflow=[]),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "steps:block:missing_workflow" in decision.reasons


def test_disallowed_agent_tool_kind_blocks_inline():
    decision = detect_inline_child(
        _playbook(workflow=[{"step": "child", "tool": {"kind": "agent"}}]),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "tool:block:step[0].kind=agent" in decision.reasons


def test_disallowed_playbook_tool_kind_blocks_inline():
    decision = detect_inline_child(
        _playbook(workflow=[{"step": "child", "tool": {"kind": "playbook"}}]),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "tool:block:step[0].kind=playbook" in decision.reasons


def test_disallowed_http_tool_kind_blocks_inline():
    decision = detect_inline_child(
        _playbook(workflow=[{"step": "call", "tool": {"kind": "http"}}]),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "tool:block:step[0].kind=http" in decision.reasons


def test_pipeline_tool_kinds_must_all_be_allowed():
    decision = detect_inline_child(
        _playbook(
            workflow=[
                {
                    "step": "pipeline",
                    "tool": [
                        {"name": "safe", "kind": "python"},
                        {"name": "unsafe", "kind": "http"},
                    ],
                }
            ]
        ),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "tool:ok:step[0].kind=python" in decision.reasons
    assert "tool:block:step[0].kind=http" in decision.reasons


def test_parallel_loop_blocks_inline():
    decision = detect_inline_child(
        _playbook(
            workflow=[
                {
                    "step": "loop",
                    "loop": {"in": "{{ items }}", "iterator": "item", "spec": {"mode": "parallel"}},
                    "tool": {"kind": "python"},
                }
            ]
        ),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "loop:block:step[0].mode=parallel" in decision.reasons


def test_cursor_loop_blocks_inline():
    decision = detect_inline_child(
        _playbook(
            workflow=[
                {
                    "step": "loop",
                    "loop": {"cursor": {"kind": "postgres"}, "iterator": "row", "spec": {"mode": "cursor"}},
                    "tool": {"kind": "python"},
                }
            ]
        ),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "loop:block:step[0].mode=cursor" in decision.reasons


def test_distributed_loop_blocks_inline():
    decision = detect_inline_child(
        _playbook(
            workflow=[
                {
                    "step": "loop",
                    "loop": {
                        "in": "{{ items }}",
                        "iterator": "item",
                        "spec": {"mode": "sequential", "policy": {"exec": "distributed"}},
                    },
                    "tool": {"kind": "python"},
                }
            ]
        ),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "loop:block:step[0].policy_exec=distributed" in decision.reasons


def test_finalizer_blocks_inline():
    decision = detect_inline_child(
        _playbook(executor={"spec": {"final_step": "cleanup"}}),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "finalizer:block:executor_spec_final_step" in decision.reasons


def test_callback_subject_blocks_inline():
    decision = detect_inline_child(
        _playbook(workflow=[{"step": "call", "spec": {"callback_subject": "reply"}, "tool": {"kind": "python"}}]),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "callback:block:callback_subject_present" in decision.reasons


def test_async_spec_blocks_inline():
    decision = detect_inline_child(
        _playbook(workflow=[{"step": "call", "spec": {"async": True}, "tool": {"kind": "python"}}]),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "async:block:spec_async_true" in decision.reasons


def test_output_ref_blocks_inline():
    decision = detect_inline_child(
        _playbook(workflow=[{"step": "call", "tool": {"kind": "python", "output_ref": "nats://ref"}}]),
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "output_ref:block:present" in decision.reasons


def test_same_tenant_mismatch_blocks_inline():
    decision = detect_inline_child(
        _playbook(metadata={"name": "child", "tenant_id": "tenant-b"}),
        {"tenant_id": "tenant-a"},
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is False
    assert "tenant_id:block:mismatch" in decision.reasons


def test_same_tenant_match_allows_inline():
    decision = detect_inline_child(
        _playbook(metadata={"name": "child", "tenant_id": "tenant-a", "organization_id": "org-a"}),
        {"workload": {"tenant_id": "tenant-a", "organization_id": "org-a"}},
        child_path="automation/agents/mcp/firestore",
    )

    assert decision.inline is True
    assert "tenant_id:ok:match" in decision.reasons
    assert "organization_id:ok:match" in decision.reasons


def test_custom_allow_list_env_csv():
    assert load_allow_list_from_env({"NOETL_INLINE_TRIVIAL_CHILDREN_ALLOW_LIST": "x/*, y/z"}) == (
        "x/*",
        "y/z",
    )


def test_allow_list_default_when_env_empty():
    assert load_allow_list_from_env({}) == DEFAULT_ALLOW_LIST


def test_decision_serializes_to_dict():
    decision = InlineDecision(inline=True, reasons=["ok"], depth=1, mode="allow_list")

    assert decision.to_dict() == {
        "inline": True,
        "reasons": ["ok"],
        "depth": 1,
        "mode": "allow_list",
    }
