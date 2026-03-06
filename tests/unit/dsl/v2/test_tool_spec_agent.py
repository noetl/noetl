"""DSL v2 ToolSpec agent kind coverage."""

from noetl.core.dsl.v2.models import ToolSpec


def test_tool_spec_accepts_agent_kind():
    tool = ToolSpec(
        kind="agent",
        framework="langchain",
        entrypoint="agents.review:build_chain",
        payload={"goal": "review this diff"},
    )
    assert tool.kind == "agent"
    assert tool.framework == "langchain"
