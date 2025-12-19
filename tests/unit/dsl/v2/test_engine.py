"""
Tests for NoETL DSL v2 Control Flow Engine
"""

import pytest
from noetl.core.dsl.v2.engine import ControlFlowEngine, PlaybookRepo, StateStore, ExecutionState
from noetl.core.dsl.v2.models import Event, Command, Playbook
from noetl.core.dsl.v2.parser import DSLParser


@pytest.fixture
def engine_setup():
    """Set up engine components."""
    playbook_repo = PlaybookRepo()
    state_store = StateStore()
    engine = ControlFlowEngine(playbook_repo, state_store)
    return engine, playbook_repo, state_store


def test_handle_workflow_start(engine_setup):
    """Test handling workflow.start event."""
    engine, playbook_repo, state_store = engine_setup
    
    # Create and register playbook
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: test_workflow

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-123")
    
    # Create workflow.start event
    event = Event(
        execution_id="exec-123",
        name="workflow.start",
        payload={}
    )
    
    # Handle event
    commands = engine.handle_event(event)
    
    # Should generate command for start step
    assert len(commands) == 1
    assert commands[0].step == "start"
    assert commands[0].tool.kind == "python"


def test_case_rule_matching(engine_setup):
    """Test case/when/then rule evaluation."""
    engine, playbook_repo, state_store = engine_setup
    
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
      endpoint: "https://api.example.com"
    
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
    playbook_repo.register(playbook, "exec-456")
    
    # Create call.done event with successful response
    event = Event(
        execution_id="exec-456",
        step="start",
        name="call.done",
        payload={
            "response": {
                "status": 200,
                "data": {"result": "success"}
            }
        }
    )
    
    # Handle event
    commands = engine.handle_event(event)
    
    # Should generate next command to 'end' step
    assert len(commands) == 1
    assert commands[0].step == "end"


def test_retry_action(engine_setup):
    """Test retry action on error."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: retry_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com"
    
    case:
      - when: "{{ event.name == 'call.done' and error is defined and error.status == 503 }}"
        then:
          retry:
            max_attempts: 3
            backoff_multiplier: 2.0
            initial_delay: 0.5
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-retry")
    
    # Create call.done event with 503 error
    event = Event(
        execution_id="exec-retry",
        step="start",
        name="call.done",
        payload={
            "error": {
                "status": 503,
                "message": "Service Unavailable"
            }
        },
        attempt=1
    )
    
    # Handle event
    commands = engine.handle_event(event)
    
    # Should generate retry command
    assert len(commands) == 1
    assert commands[0].step == "start"
    assert commands[0].attempt == 2
    assert commands[0].backoff is not None


def test_collect_action(engine_setup):
    """Test collect action for aggregation."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: collect_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com"
    
    case:
      - when: "{{ event.name == 'step.enter' }}"
        then:
          set:
            ctx:
              items: []
      
      - when: "{{ event.name == 'call.done' and response is defined }}"
        then:
          collect:
            from: response.data.items
            into: items
            mode: extend
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-collect")
    
    # First event: step.enter
    event1 = Event(
        execution_id="exec-collect",
        step="start",
        name="step.enter",
        payload={}
    )
    
    engine.handle_event(event1)
    
    # Get state
    state = state_store.get("exec-collect")
    assert "items" in state.context
    assert state.context["items"] == []
    
    # Second event: call.done with data
    event2 = Event(
        execution_id="exec-collect",
        step="start",
        name="call.done",
        payload={
            "response": {
                "data": {
                    "items": [{"id": 1}, {"id": 2}]
                }
            }
        }
    )
    
    engine.handle_event(event2)
    
    # Check that items were collected
    state = state_store.get("exec-collect")
    assert len(state.context["items"]) == 2


def test_pagination_pattern(engine_setup):
    """Test complete pagination pattern."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: pagination_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/data"
      params:
        page: 1
    
    case:
      - when: "{{ event.name == 'step.enter' }}"
        then:
          set:
            ctx:
              all_items: []
      
      - when: "{{ event.name == 'call.done' and response.paging.hasMore == true }}"
        then:
          collect:
            from: response.items
            into: all_items
            mode: extend
          call:
            params:
              page: "{{ (response.paging.page | int) + 1 }}"
      
      - when: "{{ event.name == 'call.done' and response.paging.hasMore == false }}"
        then:
          collect:
            from: response.items
            into: all_items
            mode: extend
          result:
            from: ctx.all_items
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-page")
    
    # Step enter
    event1 = Event(
        execution_id="exec-page",
        step="start",
        name="step.enter",
        payload={}
    )
    engine.handle_event(event1)
    
    # First page (hasMore=true)
    event2 = Event(
        execution_id="exec-page",
        step="start",
        name="call.done",
        payload={
            "response": {
                "items": [{"id": 1}, {"id": 2}],
                "paging": {"page": 1, "hasMore": True}
            }
        }
    )
    
    commands = engine.handle_event(event2)
    
    # Should generate call command for next page
    assert len(commands) == 1
    assert commands[0].step == "start"
    
    # Final page (hasMore=false)
    event3 = Event(
        execution_id="exec-page",
        step="start",
        name="call.done",
        payload={
            "response": {
                "items": [{"id": 3}],
                "paging": {"page": 2, "hasMore": False}
            }
        }
    )
    
    commands = engine.handle_event(event3)
    
    # Should not generate more commands (final page)
    # Result should be set in state
    state = state_store.get("exec-page")
    assert len(state.context["all_items"]) == 3


def test_conditional_transition_with_args(engine_setup):
    """Test conditional transition passing args to next step."""
    engine, playbook_repo, state_store = engine_setup
    
    yaml_content = """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: transition_test

workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: "https://api.example.com/data"
    
    case:
      - when: "{{ event.name == 'call.done' and response.status == 200 }}"
        then:
          next:
            - step: process
              args:
                data: "{{ response.data }}"
                count: "{{ response.data | length }}"

  - step: process
    tool:
      kind: python
      code: "def main(data, count): return {'processed': count}"
"""
    
    parser = DSLParser()
    playbook = parser.parse(yaml_content)
    playbook_repo.register(playbook, "exec-trans")
    
    # call.done event
    event = Event(
        execution_id="exec-trans",
        step="start",
        name="call.done",
        payload={
            "response": {
                "status": 200,
                "data": [1, 2, 3]
            }
        }
    )
    
    commands = engine.handle_event(event)
    
    # Should generate command for process step with args
    assert len(commands) == 1
    assert commands[0].step == "process"
    assert commands[0].args is not None
