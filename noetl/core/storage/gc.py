"""
Garbage collection for TempRef storage.

Strategies:
1. TTL-based: Periodic sweep of expired refs
2. Execution-finalizer: Clean up when execution completes
3. Step-finalizer: Clean up step-scoped refs when step completes
4. Workflow-finalizer: Clean up when entire workflow tree completes

Usage:
    gc = TempGarbageCollector(temp_store, scope_tracker)

    # Start background TTL sweep
    await gc.start()

    # Manual cleanup hooks
    await gc.cleanup_step(execution_id, step_name)
    await gc.cleanup_execution(execution_id)
    await gc.cleanup_workflow(root_execution_id)

    # Stop background task
    await gc.stop()
"""

import asyncio
from typing import Optional

from noetl.core.storage.temp_store import TempStore, default_store
from noetl.core.storage.scope_tracker import ScopeTracker, default_tracker
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class TempGarbageCollector:
    """
    Garbage collector for temp storage.

    Provides both periodic TTL-based cleanup and hook-based cleanup
    at scope boundaries (step complete, execution complete, workflow complete).
    """

    def __init__(
        self,
        temp_store: Optional[TempStore] = None,
        scope_tracker: Optional[ScopeTracker] = None,
        ttl_sweep_interval: int = 300,  # 5 minutes
        batch_size: int = 100
    ):
        """
        Initialize garbage collector.

        Args:
            temp_store: TempStore instance (uses default if None)
            scope_tracker: ScopeTracker instance (uses default if None)
            ttl_sweep_interval: Seconds between TTL sweeps
            batch_size: Max refs to delete per sweep batch
        """
        self.temp_store = temp_store or default_store
        self.scope_tracker = scope_tracker or default_tracker
        self.ttl_sweep_interval = ttl_sweep_interval
        self.batch_size = batch_size

        self._running = False
        self._sweep_task: Optional[asyncio.Task] = None

        # Stats
        self._ttl_deleted = 0
        self._step_deleted = 0
        self._execution_deleted = 0
        self._workflow_deleted = 0

    async def start(self):
        """Start the GC background task."""
        if self._running:
            return

        self._running = True
        self._sweep_task = asyncio.create_task(self._ttl_sweep_loop())
        logger.info(f"TEMP GC: Started (interval={self.ttl_sweep_interval}s)")

    async def stop(self):
        """Stop the GC background task."""
        self._running = False
        if self._sweep_task:
            self._sweep_task.cancel()
            try:
                await self._sweep_task
            except asyncio.CancelledError:
                pass
        logger.info("TEMP GC: Stopped")

    async def _ttl_sweep_loop(self):
        """Background loop for TTL-based cleanup."""
        while self._running:
            try:
                deleted = await self.sweep_expired()
                if deleted > 0:
                    self._ttl_deleted += deleted
                    logger.info(f"TEMP GC: Swept {deleted} expired refs (total: {self._ttl_deleted})")
            except Exception as e:
                logger.error(f"TEMP GC: Sweep error: {e}")

            await asyncio.sleep(self.ttl_sweep_interval)

    async def sweep_expired(self) -> int:
        """
        Delete all expired TempRefs.

        Returns:
            Number of refs deleted
        """
        # Get all refs from temp store cache
        deleted = 0
        for ref_str, temp_ref in list(self.temp_store._ref_cache.items()):
            if temp_ref.is_expired():
                try:
                    if await self.temp_store.delete(ref_str):
                        deleted += 1
                        if deleted >= self.batch_size:
                            break  # Batch limit reached
                except Exception as e:
                    logger.warning(f"TEMP GC: Failed to delete expired {ref_str}: {e}")

        return deleted

    async def cleanup_step(self, execution_id: str, step_name: str) -> int:
        """
        Clean up step-scoped refs when step completes.

        Args:
            execution_id: Execution ID
            step_name: Step name

        Returns:
            Number of refs deleted
        """
        refs = self.scope_tracker.get_refs_for_step_cleanup(execution_id, step_name)

        deleted = 0
        for ref in refs:
            try:
                if await self.temp_store.delete(ref):
                    deleted += 1
            except Exception as e:
                logger.warning(f"TEMP GC: Failed to delete step ref {ref}: {e}")

        if deleted > 0:
            self._step_deleted += deleted
            logger.debug(f"TEMP GC: Step cleanup for {step_name}: {deleted} refs")

        return deleted

    async def cleanup_execution(self, execution_id: str) -> int:
        """
        Clean up execution-scoped refs when execution completes.

        Args:
            execution_id: Execution ID

        Returns:
            Number of refs deleted
        """
        refs = self.scope_tracker.get_refs_for_execution_cleanup(execution_id)

        deleted = 0
        for ref in refs:
            try:
                if await self.temp_store.delete(ref):
                    deleted += 1
            except Exception as e:
                logger.warning(f"TEMP GC: Failed to delete execution ref {ref}: {e}")

        if deleted > 0:
            self._execution_deleted += deleted
            logger.info(f"TEMP GC: Execution cleanup for {execution_id}: {deleted} refs")

        return deleted

    async def cleanup_workflow(self, root_execution_id: str) -> int:
        """
        Clean up workflow-scoped refs when entire workflow tree completes.

        Args:
            root_execution_id: Root execution ID

        Returns:
            Number of refs deleted
        """
        refs = self.scope_tracker.get_refs_for_workflow_cleanup(root_execution_id)

        deleted = 0
        for ref in refs:
            try:
                if await self.temp_store.delete(ref):
                    deleted += 1
            except Exception as e:
                logger.warning(f"TEMP GC: Failed to delete workflow ref {ref}: {e}")

        if deleted > 0:
            self._workflow_deleted += deleted
            logger.info(f"TEMP GC: Workflow cleanup for {root_execution_id}: {deleted} refs")

        return deleted

    def get_stats(self) -> dict:
        """Get GC statistics."""
        return {
            "running": self._running,
            "ttl_sweep_interval": self.ttl_sweep_interval,
            "ttl_deleted": self._ttl_deleted,
            "step_deleted": self._step_deleted,
            "execution_deleted": self._execution_deleted,
            "workflow_deleted": self._workflow_deleted,
            "total_deleted": (
                self._ttl_deleted +
                self._step_deleted +
                self._execution_deleted +
                self._workflow_deleted
            ),
            "scope_stats": self.scope_tracker.get_scope_stats(),
        }


# Default GC instance
default_gc = TempGarbageCollector()


__all__ = [
    "TempGarbageCollector",
    "default_gc",
]
