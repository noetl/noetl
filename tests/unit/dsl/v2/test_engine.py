"""
Unit tests for NoETL DSL v2 - Control Flow Engine.
"""

import pytest

from noetl.core.dsl.v2.engine import (
    ControlFlowEngine,
    ExecutionState,
    PlaybookRepo,
    StateStore,
)
from noetl.core.dsl.v2.models import (
    Event,
    EventName,
    Metadata,
    Playbook,
    Step,
    ToolSpec,
    CaseEntry,
    ThenBlock,
    ActionRetry,
    ActionCall,
    ActionNext,
    ActionCollect,
)


@pytest.fixture
def playbook_repo():
    """Create playbook repository."""
    return PlaybookRepo()


@pytest.fixture
def state_store():
    """Create state store."""
    return StateStore()


@pytest.fixture
def simple_playbook():
    """Create a simple test playbook."""
    return Playbook(
        metadata=Metadata(name="test", path="test/simple"),
        workflow=[
            Step(
                step="start",
                tool=ToolSpec(kind="python", code="def main(): return {'value': 42}"),
                next="end"
            ),
            Step(
                step="end",
                tool=ToolSpec(kind="python", code="def main(): return {}")
            )
        ]
    )


@pytest.fixture
def retry_playbook():
    """Create playbook with retry logic."""
    return Playbook(
        metadata=Metadata(name="retry_test", path="test/retry"),
        workflow=[
            Step(
                step="start",
                tool=ToolSpec(
                    kind="http",
                    method="GET",
                    endpoint="https://api.example.com/data"
                ),
                case=[
                    CaseEntry(
                        when="{{ event.name == 'call.done' and error is defined and error.status == 503 }}",
                        then=ThenBlock(
                            retry=ActionRetry(
                                max_attempts=3,
                                backoff_multiplier=2.0,
                                initial_delay=0.5
                            )
                        )
                    )
                ]
            )
        ]
    )


@pytest.fixture
def pagination_playbook():
    """Create playbook with pagination logic."""
    return Playbook(
        metadata=Metadata(name="pagination_test", path="test/pagination"),
        workflow=[
            Step(
                step="start",
                tool=ToolSpec(
                    kind="http",
                    method="GET",
                    endpoint="https://api.example.com/data",
                    params={"page": 1}
                ),
                case=[
                    CaseEntry(
                        when="{{ event.name == 'step.enter' }}",
                        then=ThenBlock(
                            set={"ctx": {"pages": []}}
                        )
                    ),
                    CaseEntry(
                        when="{{ event.name == 'call.done' and response is defined and response.data.hasMore }}",
                        then=ThenBlock(
                            collect=ActionCollect(
                                from_="response.data.items",
                                into="pages",
                                mode="extend"
                            ),
                            call=ActionCall(
                                params={"page": "{{ (response.data.page | int) + 1 }}"}
                            )
                        )
                    ),
                    CaseEntry(
                        when="{{ event.name == 'call.done' and response is defined and not response.data.hasMore }}",
                        then=ThenBlock(
                            collect=ActionCollect(
                                from_="response.data.items",
                                into="pages",
                                mode="extend"
                            ),
                            next=[ActionNext(step="end")]
                        )
                    )
                ]
            ),
            Step(
                step="end",
                tool=ToolSpec(kind="python", code="def main(): return {}")
            )
        ]
    )


class TestExecutionState:
    """Test ExecutionState class."""
    
    def test_create_state(self, simple_playbook):
        """Create execution state."""
        state = ExecutionState("exec-123", simple_playbook)
        assert state.execution_id == "exec-123"
        assert state.current_step is None
        assert state.workflow_status == "running"
    
    def test_get_step(self, simple_playbook):
        """Get step by name."""
        state = ExecutionState("exec-123", simple_playbook)
        step = state.get_step("start")
        assert step is not None
        assert step.step == "start"
    
    def test_store_and_retrieve_result(self, simple_playbook):
        """Store and retrieve step result."""
        state = ExecutionState("exec-123", simple_playbook)
        state.set_step_result("start", {"value": 42})
        result = state.get_step_result("start")
        assert result["value"] == 42
    
    def test_increment_attempt(self, simple_playbook):
        """Increment attempt counter."""
        state = ExecutionState("exec-123", simple_playbook)
        assert state.increment_attempt("start") == 1
        assert state.increment_attempt("start") == 2
        assert state.increment_attempt("start") == 3


class TestControlFlowEngine:
    """Test ControlFlowEngine."""
    
    def test_workflow_start(self, playbook_repo, state_store, simple_playbook):
        """Test workflow start event."""
        playbook_repo.register(simple_playbook)
        engine = ControlFlowEngine(playbook_repo, state_store)
        
        # Mock get_by_execution to return our playbook
        original_get = playbook_repo.get_by_execution
        playbook_repo.get_by_execution = lambda exec_id: simple_playbook
        
        event = Event(
            execution_id="exec-123",
            name=EventName.WORKFLOW_START.value,
            payload={}
        )
        
        commands = engine.handle_event(event)
        
        # Should generate command for 'start' step
        assert len(commands) == 1
        assert commands[0].step == "start"
        assert commands[0].tool.kind == "python"
        
        # Restore original method
        playbook_repo.get_by_execution = original_get
    
    def test_retry_on_error(self, playbook_repo, state_store, retry_playbook):
        """Test retry logic on error."""
        playbook_repo.register(retry_playbook)
        engine = ControlFlowEngine(playbook_repo, state_store)
        
        # Initialize state
        state = ExecutionState("exec-456", retry_playbook)
        state.current_step = "start"
        state_store.save_state(state)
        
        # Simulate call.done with 503 error
        event = Event(
            execution_id="exec-456",
            step="start",
            name=EventName.CALL_DONE.value,
            payload={
                "error": {
                    "status": 503,
                    "message": "Service Unavailable"
                }
            }
        )
        
        commands = engine.handle_event(event)
        
        # Should generate retry command
        assert len(commands) == 1
        assert commands[0].step == "start"
        assert commands[0].attempt == 1
    
    def test_pagination_collect(self, playbook_repo, state_store, pagination_playbook):
        """Test pagination with collect action."""
        playbook_repo.register(pagination_playbook)
        engine = ControlFlowEngine(playbook_repo, state_store)
        
        # Initialize state
        state = ExecutionState("exec-789", pagination_playbook)
        state.current_step = "start"
        state_store.save_state(state)
        
        # Simulate step.enter to initialize context
        event_enter = Event(
            execution_id="exec-789",
            step="start",
            name=EventName.STEP_ENTER.value,
            payload={}
        )
        engine.handle_event(event_enter)
        
        # Check that pages array was initialized
        state = state_store.get_state("exec-789")
        assert "pages" in state.context
        assert state.context["pages"] == []
        
        # Simulate call.done with hasMore=true
        event_page1 = Event(
            execution_id="exec-789",
            step="start",
            name=EventName.CALL_DONE.value,
            payload={
                "response": {
                    "data": {
                        "items": [{"id": 1}, {"id": 2}],
                        "page": 1,
                        "hasMore": True
                    }
                }
            }
        )
        
        commands = engine.handle_event(event_page1)
        
        # Should generate call command for next page
        assert len(commands) == 1
        assert commands[0].step == "start"
        
        # Check that data was collected
        state = state_store.get_state("exec-789")
        assert len(state.context.get("pages", [])) > 0
    
    def test_conditional_transition(self, playbook_repo, state_store):
        """Test conditional transitions with case.then.next."""
        playbook = Playbook(
            metadata=Metadata(name="conditional", path="test/conditional"),
            workflow=[
                Step(
                    step="start",
                    tool=ToolSpec(kind="python", code="def main(): return {'flag': True}"),
                    case=[
                        CaseEntry(
                            when="{{ event.name == 'step.exit' and result.flag }}",
                            then=ThenBlock(
                                next=[ActionNext(step="path_a", args={"from": "start"})]
                            )
                        )
                    ]
                ),
                Step(
                    step="path_a",
                    tool=ToolSpec(kind="python", code="def main(): return {}")
                ),
                Step(
                    step="end",
                    tool=ToolSpec(kind="python", code="def main(): return {}")
                )
            ]
        )
        
        playbook_repo.register(playbook)
        engine = ControlFlowEngine(playbook_repo, state_store)
        
        # Initialize state
        state = ExecutionState("exec-conditional", playbook)
        state.current_step = "start"
        state.set_step_result("start", {"flag": True})
        state_store.save_state(state)
        
        # Simulate step.exit with result
        event = Event(
            execution_id="exec-conditional",
            step="start",
            name=EventName.STEP_EXIT.value,
            payload={"result": {"flag": True}}
        )
        
        commands = engine.handle_event(event)
        
        # Should generate command for path_a
        assert len(commands) == 1
        assert commands[0].step == "path_a"
        assert commands[0].args["from"] == "start"
    
    def test_structural_next(self, playbook_repo, state_store, simple_playbook):
        """Test structural (unconditional) next."""
        playbook_repo.register(simple_playbook)
        engine = ControlFlowEngine(playbook_repo, state_store)
        
        # Initialize state
        state = ExecutionState("exec-simple", simple_playbook)
        state.current_step = "start"
        state_store.save_state(state)
        
        # Simulate step.exit without case match
        event = Event(
            execution_id="exec-simple",
            step="start",
            name=EventName.STEP_EXIT.value,
            payload={"result": {"value": 42}}
        )
        
        commands = engine.handle_event(event)
        
        # Should use structural next to go to 'end'
        assert len(commands) == 1
        assert commands[0].step == "end"
