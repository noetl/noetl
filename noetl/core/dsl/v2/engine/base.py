from __future__ import annotations

from .common import *
from .state import ExecutionState
from .store import PlaybookRepo, StateStore

class EngineBase:
    _template_cache: Optional[TemplateCache] = None

    def __init__(self, playbook_repo: PlaybookRepo, state_store: StateStore):
        self.playbook_repo = playbook_repo
        self.state_store = state_store
        self.jinja_env = Environment(undefined=StrictUndefined)

        # Initialize shared template cache (singleton pattern)
        if type(self)._template_cache is None:
            type(self)._template_cache = TemplateCache(max_size=500)
        self._template_cache = type(self)._template_cache

    async def finalize_abandoned_execution(
        self,
        execution_id: str,
        reason: str = "Abandoned or timed out",
    ) -> None:
        """Forcibly finalize a stuck execution with terminal failure lifecycle events."""
        state = await self.state_store.load_state(execution_id)
        if not state:
            logger.error("[FINALIZE] No state found for execution %s", execution_id)
            return
        if state.completed:
            logger.info("[FINALIZE] Execution %s already completed; skipping", execution_id)
            return

        last_step = state.current_step or (list(state.step_results.keys())[-1] if state.step_results else None)
        logger.warning(
            "[FINALIZE] Forcibly finalizing execution %s at step %s due to: %s",
            execution_id,
            last_step,
            reason,
        )

        from noetl.core.dsl.v2.models import LifecycleEventPayload

        current_event_id = state.last_event_id
        workflow_failed_event = Event(
            execution_id=execution_id,
            step="workflow",
            name="workflow.failed",
            payload=LifecycleEventPayload(
                status="failed",
                final_step=last_step,
                result=None,
                error={"message": reason},
            ).model_dump(),
            timestamp=datetime.now(timezone.utc),
            parent_event_id=current_event_id,
        )
        await self._persist_event(workflow_failed_event, state)

        playbook_path = state.playbook.metadata.get("path", "playbook")
        playbook_failed_event = Event(
            execution_id=execution_id,
            step=playbook_path,
            name="playbook.failed",
            payload=LifecycleEventPayload(
                status="failed",
                final_step=last_step,
                result=None,
                error={"message": reason},
            ).model_dump(),
            timestamp=datetime.now(timezone.utc),
            parent_event_id=state.last_event_id,
        )
        await self._persist_event(playbook_failed_event, state)

        state.failed = True
        state.completed = True
        await self.state_store.save_state(state)
        logger.info("[FINALIZE] Emitted terminal failure lifecycle events for execution %s", execution_id)
    
