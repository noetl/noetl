from __future__ import annotations

from .common import *
from .state import ExecutionState
from .store import PlaybookRepo, StateStore

class RenderingMixin:
    def _render_value_recursive(self, value: Any, context: dict[str, Any]) -> Any:
        """Recursively render templates in nested data structures."""
        if isinstance(value, str) and "{{" in value:
            return self._render_template(value, context)
        elif isinstance(value, dict):
            return {k: self._render_value_recursive(v, context) for k, v in value.items()}
        elif isinstance(value, list):
            return [self._render_value_recursive(item, context) for item in value]
        else:
            return value
    
    def _render_template(self, template_str: str, context: dict[str, Any]) -> Any:
        """Render Jinja2 template."""
        if not isinstance(template_str, str) or "{{" not in template_str:
            return template_str
            
        try:
            # Check if this is a simple variable reference like {{ varname }} or {{ obj.attr }}
            # If so, evaluate and return the actual object instead of string representation
            import re
            # Improved regex to handle optional spaces and nested attributes
            simple_var_match = re.match(r'^\{\{\s*([\w.]+)\s*\}\}$', template_str.strip())
            if simple_var_match:
                var_path = simple_var_match.group(1)
                # Navigate dot notation: ctx.api_url → context['ctx']['api_url']
                value = context
                parts = var_path.split('.')
                
                # OPTIMIZATION: Check top-level directly first
                if len(parts) == 1:
                    part = parts[0]
                    if part in context:
                        return context[part]
                
                for part in parts:
                    if isinstance(value, dict) and part in value:
                        value = value[part]
                    elif hasattr(value, part):
                        value = getattr(value, part)
                    else:
                        # Path doesn't resolve, fall back to Jinja rendering
                        break
                else:
                    # Successfully navigated full path
                    return value
            
            # Standard Jinja2 rendering - use cached template
            template = self._template_cache.get_or_compile(self.jinja_env, template_str)
            result = template.render(**context)
            
            # Try to parse as boolean for conditions
            if result.lower() in ("true", "false"):
                return result.lower() == "true"
            
            return result
        except Exception as e:
            logger.error(
                "Template rendering error: %s | template_preview=%s | context_keys=%s",
                e,
                (template_str[:160] + "...") if isinstance(template_str, str) and len(template_str) > 160 else template_str,
                list(context.keys()) if isinstance(context, dict) else [],
            )
            raise

    def _normalize_loop_collection(self, value: Any, step_name: str) -> list[Any]:
        """Normalize loop input to a list without accidentally exploding strings into characters."""
        if isinstance(value, list):
            return value
        if value is None:
            return []
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, set):
            return list(value)
        if isinstance(value, dict):
            logger.warning(f"[LOOP] Step {step_name}: collection rendered as dict; wrapping as single item")
            return [value]
        if isinstance(value, (str, bytes, bytearray)):
            text = value.decode("utf-8", errors="replace") if not isinstance(value, str) else value
            if "{{" in text or "{%" in text:
                logger.warning(f"[LOOP] Step {step_name}: collection template unresolved, defaulting to empty list")
                return []
            logger.warning(f"[LOOP] Step {step_name}: collection rendered as scalar string; wrapping as single item")
            return [text]
        if hasattr(value, "__iter__"):
            try:
                return list(value)
            except Exception:
                logger.warning(f"[LOOP] Step {step_name}: failed to materialize iterable collection; wrapping value")
                return [value]
        return [value]

    def _build_loop_event_id_candidates(
        self,
        state: "ExecutionState",
        step_name: str,
        loop_state: Optional[dict[str, Any]] = None,
    ) -> list[str]:
        """Build ordered candidate loop identifiers for distributed-safe NATS loop state lookup."""
        candidates: list[str] = []

        loop_event_id = loop_state.get("event_id") if loop_state else None
        if loop_event_id is not None:
            candidates.append(str(loop_event_id))

        execution_fallback = f"exec_{state.execution_id}"
        if execution_fallback not in candidates:
            candidates.append(execution_fallback)

        step_event_id = state.step_event_ids.get(step_name)
        if step_event_id is not None:
            step_event_id_str = str(step_event_id)
            if step_event_id_str not in candidates:
                candidates.append(step_event_id_str)

        return candidates

    async def _ensure_loop_state_for_epoch(
        self,
        state: "ExecutionState",
        step: Step,
        event: Event,
        loop_event_id: Optional[str],
    ) -> Optional[dict[str, Any]]:
        """Hydrate per-step loop state from supervisor metadata when local memory is cold."""
        if not step.loop or not loop_event_id:
            return state.loop_state.get(step.step)

        desired_event_id = str(loop_event_id)
        existing_state = state.loop_state.get(step.step)
        if existing_state and str(existing_state.get("event_id") or "") == desired_event_id:
            return existing_state

        try:
            nats_cache = await get_nats_cache()
            nats_loop_state = await nats_cache.get_loop_state(
                str(state.execution_id),
                step.step,
                event_id=desired_event_id,
            )
        except Exception as exc:
            logger.debug(
                "[LOOP-HYDRATE] Supervisor lookup failed for %s epoch=%s: %s",
                step.step,
                desired_event_id,
                exc,
            )
            nats_loop_state = None

        if not nats_loop_state:
            return existing_state

        collection: list[Any] = []
        if existing_state and isinstance(existing_state.get("collection"), list):
            collection = list(existing_state.get("collection") or [])

        if not collection:
            try:
                context = state.get_render_context(event)
                rendered_collection = self._render_template(step.loop.in_, context)
                collection = self._normalize_loop_collection(rendered_collection, step.step)
            except Exception as exc:
                logger.warning(
                    "[LOOP-HYDRATE] Failed to render loop collection for %s epoch=%s: %s",
                    step.step,
                    desired_event_id,
                    exc,
                )

        if not collection:
            return existing_state

        state.init_loop(
            step.step,
            collection,
            step.loop.iterator,
            step.loop.mode,
            event_id=desired_event_id,
        )
        loop_state = state.loop_state[step.step]

        completed_count = int(nats_loop_state.get("completed_count", 0) or 0)
        scheduled_count = max(
            int(nats_loop_state.get("scheduled_count", completed_count) or completed_count),
            completed_count,
        )
        loop_state["event_id"] = desired_event_id
        loop_state["index"] = min(completed_count, len(collection))
        loop_state["scheduled_count"] = min(scheduled_count, len(collection))
        if completed_count > 0 and not loop_state.get("results"):
            loop_state["omitted_results_count"] = completed_count
        if nats_loop_state.get("loop_done_claimed", False):
            loop_state["completed"] = True
            loop_state["aggregation_finalized"] = True
        return loop_state

    @staticmethod
    def _loop_event_ids_compatible(
        cached_event_id: Optional[str],
        restored_event_id: Optional[str],
    ) -> bool:
        """Allow safe loop snapshot reuse across replay key normalization."""
        if cached_event_id is None or restored_event_id is None:
            return True
        cached = str(cached_event_id)
        restored = str(restored_event_id)
        if cached == restored:
            return True

        # Compatibility fallback: allow exec-key matches only for the same execution key.
        # Do not treat exec_<id> as a wildcard against loop_<...> or numeric step event ids.
        if cached.startswith("exec_") and restored.startswith("exec_"):
            return cached == restored

        return False

    def _snapshot_loop_collections(
        self,
        state: "ExecutionState",
    ) -> dict[str, dict[str, Any]]:
        """Capture active loop collection snapshots before cache invalidation."""
        snapshots: dict[str, dict[str, Any]] = {}
        for step_name, loop_state in state.loop_state.items():
            collection = loop_state.get("collection")
            if not isinstance(collection, list) or len(collection) == 0:
                continue
            epoch_size = len(collection)
            # Cap counts to epoch_size so accumulated multi-batch counts don't inflate the snapshot.
            # After a state rebuild, state.get_loop_completed_count() returns the total across all
            # epochs; capping to epoch_size keeps the snapshot epoch-relative.
            completed_count = min(state.get_loop_completed_count(step_name), epoch_size)
            scheduled_count = min(
                int(loop_state.get("scheduled_count", completed_count) or completed_count),
                epoch_size,
            )
            if scheduled_count < completed_count:
                scheduled_count = completed_count
            snapshots[step_name] = {
                "collection": list(collection),
                "epoch_size": epoch_size,
                "event_id": (
                    str(loop_state.get("event_id"))
                    if loop_state.get("event_id") is not None
                    else None
                ),
                "iterator": loop_state.get("iterator"),
                "mode": loop_state.get("mode"),
                "completed_count": completed_count,
                "scheduled_count": scheduled_count,
            }
        return snapshots

    def _restore_loop_collection_snapshots(
        self,
        state: "ExecutionState",
        snapshots: dict[str, dict[str, Any]],
    ) -> int:
        """Restore loop collections that replay could not reconstruct safely."""
        restored_count = 0
        for step_name, snapshot in snapshots.items():
            loop_state = state.loop_state.get(step_name)
            if not loop_state:
                continue

            cached_collection = snapshot.get("collection")
            if not isinstance(cached_collection, list) or len(cached_collection) == 0:
                continue

            restored_event_id = (
                str(loop_state.get("event_id"))
                if loop_state.get("event_id") is not None
                else None
            )
            cached_event_id = snapshot.get("event_id")
            if not self._loop_event_ids_compatible(cached_event_id, restored_event_id):
                continue

            current_collection = loop_state.get("collection")
            current_size = (
                len(current_collection)
                if isinstance(current_collection, list)
                else 0
            )
            cached_size = len(cached_collection)
            snapshot_completed_count = int(
                snapshot.get("completed_count", 0) or 0
            )
            snapshot_scheduled_count = int(
                snapshot.get("scheduled_count", snapshot_completed_count)
                or snapshot_completed_count
            )
            if snapshot_scheduled_count < snapshot_completed_count:
                snapshot_scheduled_count = snapshot_completed_count

            # Use epoch_size from snapshot (= len(collection) at snapshot time) to cap
            # min_required_size.  Accumulated completion counts span multiple batches and
            # would falsely inflate the threshold beyond the per-epoch batch size, causing
            # valid same-epoch snapshots to be rejected after the first batch.
            snapshot_epoch_size_raw = snapshot.get("epoch_size")
            snapshot_epoch_size = int(snapshot_epoch_size_raw or 0)
            completed_count = max(
                state.get_loop_completed_count(step_name),
                snapshot_completed_count,
            )
            scheduled_count = max(
                snapshot_scheduled_count,
                completed_count,
            )
            if snapshot_epoch_size > 0:
                completed_count = min(completed_count, snapshot_epoch_size)
                scheduled_count = min(scheduled_count, snapshot_epoch_size)
                min_required_size = max(
                    1,
                    min(completed_count, snapshot_epoch_size),
                    min(scheduled_count, snapshot_epoch_size),
                )
            else:
                min_required_size = max(1, completed_count, scheduled_count)

            loop_mode = str(loop_state.get("mode") or snapshot.get("mode") or "").lower()
            if (
                loop_mode == "parallel"
                and cached_size <= 1
                and (scheduled_count > cached_size or completed_count > cached_size)
            ):
                logger.warning(
                    "[LOOP-CACHE-RESTORE] Skipping tiny parallel snapshot for %s "
                    "(cached_size=%s scheduled=%s completed=%s snapshot_scheduled=%s snapshot_completed=%s)",
                    step_name,
                    cached_size,
                    scheduled_count,
                    completed_count,
                    snapshot_scheduled_count,
                    snapshot_completed_count,
                )
                continue

            if cached_size < min_required_size:
                logger.warning(
                    "[LOOP-CACHE-RESTORE] Skipping snapshot restore for %s "
                    "(cached_size=%s required_min=%s scheduled=%s completed=%s "
                    "snapshot_scheduled=%s snapshot_completed=%s cached_event_id=%s restored_event_id=%s)",
                    step_name,
                    cached_size,
                    min_required_size,
                    scheduled_count,
                    completed_count,
                    snapshot_scheduled_count,
                    snapshot_completed_count,
                    cached_event_id,
                    restored_event_id,
                )
                continue

            should_restore = (
                current_size == 0
                or (current_size <= min_required_size and cached_size > current_size)
            )
            if not should_restore:
                continue

            loop_state["collection"] = list(cached_collection)
            if not loop_state.get("iterator") and snapshot.get("iterator") is not None:
                loop_state["iterator"] = snapshot.get("iterator")
            if not loop_state.get("mode") and snapshot.get("mode") is not None:
                loop_state["mode"] = snapshot.get("mode")
            loop_state["scheduled_count"] = scheduled_count
            restored_count += 1
            logger.warning(
                "[LOOP-CACHE-RESTORE] Restored collection snapshot for %s "
                "(cached_size=%s replay_size=%s scheduled=%s completed=%s "
                "snapshot_scheduled=%s snapshot_completed=%s cached_event_id=%s restored_event_id=%s)",
                step_name,
                cached_size,
                current_size,
                scheduled_count,
                completed_count,
                snapshot_scheduled_count,
                snapshot_completed_count,
                cached_event_id,
                restored_event_id,
            )

            # After a STATE-CACHE-STALE rebuild mid-epoch, load_state accumulates results
            # from ALL prior epochs in loop_state["results"] + omitted_results_count.
            # This inflates get_loop_completed_count() to a cross-epoch total (e.g. 806 for
            # a 10×100 loop), causing previous_exhausted=True in _create_command_for_step
            # even though only ~5/100 iterations of the current epoch have completed.
            # Fix: when the cross-epoch total exceeds one epoch's size, reset results/counts
            # and index to the snapshot's epoch-relative values so downstream exhaustion
            # checks operate on the current epoch only.
            if snapshot_epoch_size > 0 and completed_count > snapshot_epoch_size:
                # Use modulus to get the actual completed/scheduled count within the CURRENT epoch,
                # ensuring that exactly completing a multiple of epoch_size returns the full size,
                # rather than 0, unless no work has been done in the current epoch.
                # Prefer the explicit epoch-scoped progress tracked in the NATS snapshot,
                # falling back to modulus estimation if the snapshot is empty/missing.
                epoch_relative_count = snapshot_completed_count
                if epoch_relative_count == 0 and completed_count > 0 and (completed_count % snapshot_epoch_size) > 0:
                    epoch_relative_count = completed_count % snapshot_epoch_size
                elif epoch_relative_count == 0 and completed_count > 0 and (completed_count % snapshot_epoch_size) == 0:
                    epoch_relative_count = snapshot_epoch_size
                    
                epoch_relative_scheduled = snapshot_scheduled_count
                if epoch_relative_scheduled == 0 and scheduled_count > 0 and (scheduled_count % snapshot_epoch_size) > 0:
                    epoch_relative_scheduled = scheduled_count % snapshot_epoch_size
                elif epoch_relative_scheduled == 0 and scheduled_count > 0 and (scheduled_count % snapshot_epoch_size) == 0:
                    epoch_relative_scheduled = snapshot_epoch_size
                
                # Do NOT unconditionally clear results array here. 
                # This causes the engine to forget completed iterations if the rebuilt epoch matches the cached epoch.
                # Only collapse the array if we are synthesizing an entirely new relative count and missing the granular results.
                # It is safer to truncate to omitted_results_count=epoch_relative_count if and only if we truly lost the granular results.
                # However, load_state ALREADY properly clears `results` when crossing an epoch boundary (via command.issued).
                # The only time we are here is if the cross-epoch total leaked into the current iteration state.
                if len(loop_state.get("results", [])) > epoch_relative_count:
                    loop_state["results"] = loop_state.get("results", [])[-epoch_relative_count:]
                loop_state["omitted_results_count"] = max(0, epoch_relative_count - len(loop_state.get("results", [])))
                loop_state["index"] = epoch_relative_count
                loop_state["scheduled_count"] = epoch_relative_scheduled
                logger.warning(
                    "[LOOP-CACHE-RESTORE] Reset loop counts to epoch-relative for %s "
                    "(cross_epoch_total=%s epoch_size=%s epoch_relative=%s epoch_scheduled=%s)",
                    step_name,
                    completed_count,
                    snapshot_epoch_size,
                    epoch_relative_count,
                    epoch_relative_scheduled,
                )

        return restored_count
