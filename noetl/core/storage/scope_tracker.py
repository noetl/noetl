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

        # ref -> scope keys index for O(1) unregistration on cache eviction
        self._ref_index: Dict[str, Set[str]] = {}

    @staticmethod
    def _step_scope_key(execution_id: str, step_name: str) -> str:
        return f"{execution_id}:{step_name}"

    @staticmethod
    def _step_ref_index_key(scope_key: str) -> str:
        return f"step:{scope_key}"

    @staticmethod
    def _execution_ref_index_key(execution_id: str) -> str:
        return f"exec:{execution_id}"

    def _index_ref(self, ref: str, ref_index_key: str) -> None:
        self._ref_index.setdefault(ref, set()).add(ref_index_key)

    def _drop_scope_refs_from_index(self, ref_index_key: str, refs: List[str]) -> None:
        for ref in refs:
            scope_keys = self._ref_index.get(ref)
            if not scope_keys:
                continue
            scope_keys.discard(ref_index_key)
            if not scope_keys:
                self._ref_index.pop(ref, None)

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
            scope_key = self._step_scope_key(execution_id, step_name)
            if scope_key not in self._step_scopes:
                self._step_scopes[scope_key] = ScopeContext(
                    execution_id=execution_id,
                    scope=scope,
                    step_name=step_name
                )
            self._step_scopes[scope_key].refs.add(ref_str)
            self._index_ref(ref_str, self._step_ref_index_key(scope_key))
            logger.debug(f"SCOPE: Registered step-scoped ref {ref_str} for {scope_key}")

        elif scope == Scope.EXECUTION:
            if execution_id not in self._execution_scopes:
                self._execution_scopes[execution_id] = ScopeContext(
                    execution_id=execution_id,
                    scope=scope,
                    parent_execution_id=parent_execution_id
                )
            self._execution_scopes[execution_id].refs.add(ref_str)
            self._index_ref(ref_str, self._execution_ref_index_key(execution_id))
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
            self._index_ref(ref_str, self._execution_ref_index_key(root_id))
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
        scope_key = self._step_scope_key(execution_id, step_name)
        if scope_key in self._step_scopes:
            refs = list(self._step_scopes[scope_key].refs)
            del self._step_scopes[scope_key]
            self._drop_scope_refs_from_index(self._step_ref_index_key(scope_key), refs)
            logger.debug(f"SCOPE: Step cleanup for {scope_key}: {len(refs)} refs")
            return refs
        return []

    def unregister_ref(self, ref: str) -> None:
        """
        Remove a ref from all tracked scopes.

        This is used when TempStore evicts cache entries to keep scope tracking
        bounded and avoid stale tracker-only references.
        """
        removed = False
        scope_keys = self._ref_index.pop(ref, set())
        if not scope_keys:
            return

        for scope_key in scope_keys:
            if scope_key.startswith("step:"):
                step_scope_key = scope_key[len("step:"):]
                ctx = self._step_scopes.get(step_scope_key)
                if ctx and ref in ctx.refs:
                    ctx.refs.discard(ref)
                    removed = True
                    if not ctx.refs:
                        del self._step_scopes[step_scope_key]
            elif scope_key.startswith("exec:"):
                execution_id = scope_key[len("exec:"):]
                ctx = self._execution_scopes.get(execution_id)
                if ctx and ref in ctx.refs:
                    ctx.refs.discard(ref)
                    removed = True
                    if not ctx.refs:
                        del self._execution_scopes[execution_id]

        if removed:
            logger.debug("SCOPE: Unregistered ref %s", ref)

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
                execution_refs = list(scope_ctx.refs)
                refs.extend(execution_refs)
                del self._execution_scopes[execution_id]
                self._drop_scope_refs_from_index(
                    self._execution_ref_index_key(execution_id),
                    execution_refs,
                )

        # Get any remaining step refs
        step_keys = [k for k in self._step_scopes if k.startswith(f"{execution_id}:")]
        for key in step_keys:
            step_refs = list(self._step_scopes[key].refs)
            refs.extend(step_refs)
            del self._step_scopes[key]
            self._drop_scope_refs_from_index(self._step_ref_index_key(key), step_refs)

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
                workflow_refs = list(scope_ctx.refs)
                refs.extend(workflow_refs)
                del self._execution_scopes[root_execution_id]
                self._drop_scope_refs_from_index(
                    self._execution_ref_index_key(root_execution_id),
                    workflow_refs,
                )

        logger.info(f"SCOPE: Workflow cleanup for {root_execution_id}: {len(refs)} refs")
        return refs

    def get_scope_stats(self) -> Dict[str, int]:
        """Get statistics about tracked scopes."""
        return {
            "execution_scopes": len(self._execution_scopes),
            "step_scopes": len(self._step_scopes),
            "workflow_trees": len(self._workflow_tree),
            "indexed_refs": len(self._ref_index),
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
