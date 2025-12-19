"""
Tests for NoETL DSL v2 Parser
"""

import pytest
from noetl.core.dsl.v2.parser import DSLParser, parse_playbook
from noetl.core.dsl.v2.models import Playbook, Step, ToolSpec


def test_parse_simple_playbook():
    """Test parsing a simple v2 playbook."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test_playbook
  path: test/simple

workload:
  api_url: "https://api.example.com"

workflow:
  - step: start
    desc: "Start step"
    tool:
      kind: http
      method: GET
      endpoint: "{{ workload.api_url }}/test"
    
    next: end

  - step: end
    desc: "End step"
    tool:
      kind: python
      code: |
        def main():
            return {"status": "done"}
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    
    assert playbook.apiVersion == "noetl.io/v2"
    assert playbook.kind == "Playbook"
    assert playbook.metadata["name"] == "test_playbook"
    assert len(playbook.workflow) == 2
    assert playbook.workflow[0].step == "start"
    assert playbook.workflow[0].tool.kind == "http"
    assert playbook.workflow[1].step == "end"


def test_parse_with_case():
    """Test parsing playbook with case/when/then."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: case_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/data"
    
    case:
      - when: "{{ event.name == 'call.done' and response.status == 200 }}"
        then:
          result:
            from: response.data
          next:
            - step: end

  - step: end
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    
    assert len(playbook.workflow) == 2
    start_step = playbook.workflow[0]
    assert start_step.case is not None
    assert len(start_step.case) == 1
    assert "event.name ==" in start_step.case[0].when


def test_reject_old_type_field():
    """Test that old 'type' field is rejected."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: old_style

workflow:
  - step: start
    type: http
    url: "https://api.example.com"
"""
    
    parser = DSLParser()
    with pytest.raises(ValueError, match="'type' field is not allowed"):
        parser.parse(yaml_content)


def test_reject_next_with_when():
    """Test that old next.when/then/else is rejected."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: old_next

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com"
    
    next:
      - when: "{{ some_condition }}"
        then:
          - step: end
"""
    
    parser = DSLParser()
    with pytest.raises(ValueError, match="Conditional 'next' with when/then/else is not allowed"):
        parser.parse(yaml_content)


def test_require_start_step():
    """Test that workflow must have 'start' step."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: no_start

workflow:
  - step: begin
    tool:
      kind: python
      code: "def main(): pass"
"""
    
    parser = DSLParser()
    with pytest.raises(ValueError, match="must have a step named 'start'"):
        parser.parse(yaml_content)


def test_require_tool_kind():
    """Test that tool must have 'kind' field."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: no_kind

workflow:
  - step: start
    tool:
      method: GET
      url: "https://api.example.com"
"""
    
    parser = DSLParser()
    with pytest.raises(ValueError, match="must have 'kind' field"):
        parser.parse(yaml_content)


def test_parse_with_loop():
    """Test parsing step with loop."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: loop_test

workload:
  items:
    - name: "item1"
    - name: "item2"

workflow:
  - step: start
    desc: "Loop over items"
    loop:
      in: "{{ workload.items }}"
      iterator: item
    
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/{{ item.name }}"
    
    next: end

  - step: end
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    
    start_step = playbook.workflow[0]
    assert start_step.loop is not None
    assert start_step.loop.in_ == "{{ workload.items }}"
    assert start_step.loop.iterator == "item"


def test_parse_file(tmp_path):
    """Test parsing from file."""
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: file_test

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    test_file = tmp_path / "test_playbook.yaml"
    test_file.write_text(yaml_content)
    
    parser = DSLParser()
    playbook = parser.parse_file(test_file)
    
    assert playbook.metadata["name"] == "file_test"


def test_validate_function():
    """Test validation function."""
    valid_yaml = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: valid

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    invalid_yaml = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: invalid

workflow:
  - step: not_start
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    parser = DSLParser()
    
    is_valid, error = parser.validate(valid_yaml)
    assert is_valid
    assert error is None
    
    is_valid, error = parser.validate(invalid_yaml)
    assert not is_valid
    assert "start" in error
