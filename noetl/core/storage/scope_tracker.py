"""
Scope tracking for TempRef lifecycle management.

Tracks which refs belong to which scope and triggers cleanup
when scope boundaries are crossed.

Scopes:
- step: Cleaned up when step completes
- execution: Cleaned up when playbook completes
- workflow: Persists across nested playbook calls, cleaned up when root completes
"""

from typing import Dict, List, Set, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

from noetl.core.storage.models import TempRef, Scope
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


@dataclass
class ScopeContext:
    """Context for a scope boundary."""
    execution_id: str
    scope: Scope
    parent_execution_id: Optional[str] = None
    step_name: Optional[str] = None
    refs: Set[str] = field(default_factory=set)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ScopeTracker:
    """
    Tracks refs by scope for cleanup.

    Scope hierarchy:
    - workflow: shared across nested playbook calls
    - execution: cleaned up when playbook completes
    - step: cleaned up when step completes

    Usage:
        tracker = ScopeTracker()

        # Register refs
        tracker.register_ref(temp_ref, execution_id="123", step_name="fetch_data")

        # Get refs to clean up when step completes
        refs = tracker.get_refs_for_step_cleanup("123", "fetch_data")

        # Get refs to clean up when execution completes
        refs = tracker.get_refs_for_execution_cleanup("123")
    """

    def __init__(self):
        # execution_id -> ScopeContext
        self._execution_scopes: Dict[str, ScopeContext] = {}

        # execution_id:step_name -> ScopeContext
        self._step_scopes: Dict[str, ScopeContext] = {}

        # parent_execution_id -> Set[child_execution_ids]
        self._workflow_tree: Dict[str, Set[str]] = {}

        # root execution for workflow scope
        self._workflow_roots: Dict[str, str] = {}  # execution_id -> root_execution_id

    def register_ref(
        self,
        ref: TempRef,
        execution_id: str,
        step_name: Optional[str] = None,
        parent_execution_id: Optional[str] = None
    ):
        """
        Register a TempRef in its scope.

        Args:
            ref: TempRef to register
            execution_id: Current execution ID
            step_name: Current step name (required for step scope)
            parent_execution_id: Parent execution ID (for workflow scope tracking)
        """
        scope = ref.scope
        ref_str = ref.ref

        if scope == Scope.STEP:
            if not step_name:
                raise ValueError("step_name required for step-scoped refs")
            key = f"{execution_id}:{step_name}"
            if key not in self._step_scopes:
                self._step_scopes[key] = ScopeContext(
                    execution_id=execution_id,
                    scope=scope,
                    step_name=step_name
                )
            self._step_scopes[key].refs.add(ref_str)
            logger.debug(f"SCOPE: Registered step-scoped ref {ref_str} for {key}")

        elif scope == Scope.EXECUTION:
            if execution_id not in self._execution_scopes:
                self._execution_scopes[execution_id] = ScopeContext(
                    execution_id=execution_id,
                    scope=scope,
                    parent_execution_id=parent_execution_id
                )
            self._execution_scopes[execution_id].refs.add(ref_str)
            logger.debug(f"SCOPE: Registered execution-scoped ref {ref_str}")

        elif scope == Scope.WORKFLOW:
            # Workflow scope attaches to root execution
            root_id = self._get_workflow_root(execution_id, parent_execution_id)

            if root_id not in self._execution_scopes:
                self._execution_scopes[root_id] = ScopeContext(
                    execution_id=root_id,
                    scope=Scope.WORKFLOW
                )
            self._execution_scopes[root_id].refs.add(ref_str)
            logger.debug(f"SCOPE: Registered workflow-scoped ref {ref_str} (root={root_id})")

            # Track workflow tree
            if parent_execution_id:
                if parent_execution_id not in self._workflow_tree:
                    self._workflow_tree[parent_execution_id] = set()
                self._workflow_tree[parent_execution_id].add(execution_id)

    def _get_workflow_root(self, execution_id: str, parent_execution_id: Optional[str]) -> str:
        """Get the root execution ID for workflow scope."""
        if execution_id in self._workflow_roots:
            return self._workflow_roots[execution_id]

        if parent_execution_id:
            # Recursively find root
            root = self._get_workflow_root(parent_execution_id, None)
            self._workflow_roots[execution_id] = root
            return root

        # This is the root
        self._workflow_roots[execution_id] = execution_id
        return execution_id

    def get_refs_for_step_cleanup(self, execution_id: str, step_name: str) -> List[str]:
        """
        Get refs to clean up when step completes.

        Args:
            execution_id: Execution ID
            step_name: Step name

        Returns:
            List of ref URIs to clean up
        """
        key = f"{execution_id}:{step_name}"
        if key in self._step_scopes:
            refs = list(self._step_scopes[key].refs)
            del self._step_scopes[key]
            logger.debug(f"SCOPE: Step cleanup for {key}: {len(refs)} refs")
            return refs
        return []

    def get_refs_for_execution_cleanup(self, execution_id: str) -> List[str]:
        """
        Get refs to clean up when execution completes.

        Args:
            execution_id: Execution ID

        Returns:
            List of ref URIs to clean up
        """
        refs = []

        # Get direct execution refs
        if execution_id in self._execution_scopes:
            scope_ctx = self._execution_scopes[execution_id]
            # Only clean execution-scoped refs, not workflow-scoped
            if scope_ctx.scope == Scope.EXECUTION:
                refs.extend(scope_ctx.refs)
                del self._execution_scopes[execution_id]

        # Get any remaining step refs
        step_keys = [k for k in self._step_scopes if k.startswith(f"{execution_id}:")]
        for key in step_keys:
            refs.extend(self._step_scopes[key].refs)
            del self._step_scopes[key]

        logger.debug(f"SCOPE: Execution cleanup for {execution_id}: {len(refs)} refs")
        return refs

    def get_refs_for_workflow_cleanup(self, root_execution_id: str) -> List[str]:
        """
        Get refs to clean up when workflow (including sub-playbooks) completes.

        Args:
            root_execution_id: Root execution ID

        Returns:
            List of ref URIs to clean up
        """
        refs = []

        def collect_tree(exec_id: str):
            # Collect refs for this execution
            refs.extend(self.get_refs_for_execution_cleanup(exec_id))

            # Collect from children
            if exec_id in self._workflow_tree:
                for child_id in list(self._workflow_tree[exec_id]):
                    collect_tree(child_id)
                del self._workflow_tree[exec_id]

            # Clean up workflow root tracking
            self._workflow_roots.pop(exec_id, None)

        collect_tree(root_execution_id)

        # Also clean up workflow-scoped refs attached to root
        if root_execution_id in self._execution_scopes:
            scope_ctx = self._execution_scopes[root_execution_id]
            if scope_ctx.scope == Scope.WORKFLOW:
                refs.extend(scope_ctx.refs)
                del self._execution_scopes[root_execution_id]

        logger.info(f"SCOPE: Workflow cleanup for {root_execution_id}: {len(refs)} refs")
        return refs

    def get_scope_stats(self) -> Dict[str, int]:
        """Get statistics about tracked scopes."""
        return {
            "execution_scopes": len(self._execution_scopes),
            "step_scopes": len(self._step_scopes),
            "workflow_trees": len(self._workflow_tree),
            "total_refs": sum(
                len(ctx.refs) for ctx in self._execution_scopes.values()
            ) + sum(
                len(ctx.refs) for ctx in self._step_scopes.values()
            )
        }


# Default tracker instance
default_tracker = ScopeTracker()


__all__ = [
    "ScopeContext",
    "ScopeTracker",
    "default_tracker",
]
