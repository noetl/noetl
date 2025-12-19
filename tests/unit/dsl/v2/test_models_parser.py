"""
Unit tests for NoETL DSL v2 - Models and Parser.
"""

import pytest
from pydantic import ValidationError

from noetl.core.dsl.v2 import (
    ActionCall,
    ActionNext,
    ActionRetry,
    CaseEntry,
    Loop,
    Metadata,
    Playbook,
    Step,
    ThenBlock,
    ToolSpec,
)
from noetl.core.dsl.v2.parser import parse_playbook_yaml


class TestModels:
    """Test Pydantic models validation."""
    
    def test_tool_spec_requires_kind(self):
        """ToolSpec must have kind field."""
        with pytest.raises(ValidationError, match="kind"):
            ToolSpec()
    
    def test_tool_spec_http(self):
        """HTTP tool with method and endpoint."""
        tool = ToolSpec(
            kind="http",
            method="GET",
            endpoint="https://api.example.com/data",
            headers={"X-API-Key": "secret"}
        )
        assert tool.kind == "http"
        assert tool.method == "GET"
        assert tool.endpoint == "https://api.example.com/data"
    
    def test_tool_spec_postgres(self):
        """Postgres tool with auth and command."""
        tool = ToolSpec(
            kind="postgres",
            auth="pg_local",
            command="SELECT * FROM users WHERE id = 1"
        )
        assert tool.kind == "postgres"
        assert tool.auth == "pg_local"
        assert "SELECT" in tool.command
    
    def test_tool_spec_python(self):
        """Python tool with code."""
        tool = ToolSpec(
            kind="python",
            code="def main(x): return x * 2"
        )
        assert tool.kind == "python"
        assert "def main" in tool.code
    
    def test_loop_validation(self):
        """Loop requires in and iterator."""
        loop = Loop(in_="{{ workload.items }}", iterator="item")
        assert loop.iterator == "item"
        
        with pytest.raises(ValidationError):
            Loop(in_="items")  # missing iterator
    
    def test_case_entry_validation(self):
        """CaseEntry requires when and then."""
        case = CaseEntry(
            when="{{ event.name == 'call.done' }}",
            then=ThenBlock(
                retry=ActionRetry(max_attempts=3)
            )
        )
        assert "call.done" in case.when
        assert case.then.retry.max_attempts == 3
    
    def test_then_block_requires_action(self):
        """ThenBlock must have at least one action."""
        with pytest.raises(ValidationError, match="at least one action"):
            ThenBlock()
    
    def test_step_validation(self):
        """Step requires step name and tool."""
        step = Step(
            step="fetch_data",
            tool=ToolSpec(kind="http", method="GET", endpoint="https://api.example.com")
        )
        assert step.step == "fetch_data"
        assert step.tool.kind == "http"
    
    def test_step_rejects_conditional_next(self):
        """Step-level next must be unconditional."""
        with pytest.raises(ValidationError, match="unconditional"):
            Step(
                step="test",
                tool=ToolSpec(kind="python", code="pass"),
                next={"when": "{{ flag }}", "then": "next_step"}
            )
    
    def test_playbook_requires_start_step(self):
        """Playbook must have a 'start' step."""
        with pytest.raises(ValidationError, match="start"):
            Playbook(
                metadata=Metadata(name="test", path="test/path"),
                workflow=[
                    Step(
                        step="other_step",
                        tool=ToolSpec(kind="python", code="pass")
                    )
                ]
            )
    
    def test_playbook_validates_next_references(self):
        """Playbook validates that next step references exist."""
        with pytest.raises(ValidationError, match="non-existent"):
            Playbook(
                metadata=Metadata(name="test", path="test/path"),
                workflow=[
                    Step(
                        step="start",
                        tool=ToolSpec(kind="python", code="pass"),
                        next="missing_step"
                    )
                ]
            )


class TestParser:
    """Test YAML parser."""
    
    def test_parse_minimal_playbook(self):
        """Parse minimal valid playbook."""
        yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: minimal
  path: test/minimal
workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
  - step: end
    tool:
      kind: python
      code: "def main(): return {}"
"""
        playbook = parse_playbook_yaml(yaml_content)
        assert playbook.metadata.name == "minimal"
        assert len(playbook.workflow) == 2
        assert playbook.workflow[0].step == "start"
    
    def test_parse_playbook_with_loop(self):
        """Parse playbook with loop."""
        yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: loop_test
  path: test/loop
workflow:
  - step: start
    loop:
      in: "{{ workload.items }}"
      iterator: item
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/{{ item.id }}"
"""
        playbook = parse_playbook_yaml(yaml_content)
        assert playbook.workflow[0].loop is not None
        assert playbook.workflow[0].loop.iterator == "item"
    
    def test_parse_playbook_with_case(self):
        """Parse playbook with case/when/then."""
        yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: case_test
  path: test/case
workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: https://api.example.com/data
    case:
      - when: "{{ event.name == 'call.done' and error is defined }}"
        then:
          retry:
            max_attempts: 3
            backoff_multiplier: 2.0
            initial_delay: 0.5
"""
        playbook = parse_playbook_yaml(yaml_content)
        assert playbook.workflow[0].case is not None
        assert len(playbook.workflow[0].case) == 1
        assert playbook.workflow[0].case[0].then.retry.max_attempts == 3
    
    def test_parse_playbook_with_workload(self):
        """Parse playbook with workload variables."""
        yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: workload_test
  path: test/workload
workload:
  api_url: https://api.example.com
  threshold: 100
workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
"""
        playbook = parse_playbook_yaml(yaml_content)
        assert playbook.workload is not None
        assert playbook.workload["api_url"] == "https://api.example.com"
        assert playbook.workload["threshold"] == 100
    
    def test_invalid_yaml_raises_error(self):
        """Invalid YAML raises error."""
        with pytest.raises(Exception):
            parse_playbook_yaml("invalid: yaml: content:")
    
    def test_missing_required_fields_raises_error(self):
        """Missing required fields raises ValidationError."""
        yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: incomplete
"""
        with pytest.raises(ValidationError):
            parse_playbook_yaml(yaml_content)


class TestActionModels:
    """Test action models."""
    
    def test_action_retry(self):
        """ActionRetry validation."""
        retry = ActionRetry(max_attempts=5, backoff_multiplier=1.5)
        assert retry.max_attempts == 5
        assert retry.backoff_multiplier == 1.5
        
        with pytest.raises(ValidationError):
            ActionRetry(max_attempts=0)  # must be >= 1
    
    def test_action_call(self):
        """ActionCall for tool re-invocation."""
        call = ActionCall(
            params={"page": 2},
            endpoint="https://api.example.com/page/2"
        )
        assert call.params["page"] == 2
    
    def test_action_next(self):
        """ActionNext for conditional transitions."""
        next_action = ActionNext(
            step="target_step",
            args={"data": "value"}
        )
        assert next_action.step == "target_step"
        assert next_action.args["data"] == "value"
