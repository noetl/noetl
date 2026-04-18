from __future__ import annotations

from .common import *

class ExecutionState:
    """Tracks state of a playbook execution."""
    
    def __init__(self, execution_id: str, playbook: Playbook, payload: dict[str, Any], catalog_id: Optional[int] = None, parent_execution_id: Optional[int] = None):
        self.execution_id = execution_id
        self.playbook = playbook
        self.payload = payload
        self.catalog_id = catalog_id  # Store catalog_id for event persistence
        self.parent_execution_id = parent_execution_id  # Track parent execution for sub-playbooks
        self.current_step: Optional[str] = None
        self.variables: dict[str, Any] = {}
        self.last_event_id: Optional[int] = None  # Track last persisted event ID
        self.step_event_ids: dict[str, int] = {}  # Track last event per step
        self.step_results: dict[str, Any] = {}
        self.completed_steps: set[str] = set()
        self.issued_steps: set[str] = set()  # Track steps that have commands issued (pending execution)
        self.failed = False
        self.completed = False
        
        # Root event tracking for traceability
        self.root_event_id: Optional[int] = None  # First event (playbook.initialized) for full trace
        
        # Loop state tracking
        self.loop_state: dict[str, dict[str, Any]] = {}  # step_name -> {collection, index, item, mode}
        self.step_stall_counts: dict[str, int] = {}  # step_name -> consecutive times loop ended with zero successful slots
        self.emitted_loop_epochs: set[str] = set()  # "step_name:event_name:loop_event_id"


        # Pagination state tracking for collect+retry pattern
        self.pagination_state: dict[str, dict[str, Any]] = {}  # step_name -> {collected_data: [], iteration_count: int}

        # Deferred next actions tracking for inline tasks
        # When inline tasks are in a then block with next actions, the next is deferred until inline tasks complete
        self.pending_next_actions: dict[str, dict[str, Any]] = {}  # inline_task_step -> {next_actions, inline_tasks, context_event_step}
        
        # Initialize workload variables (becomes ctx at runtime)
        # NOTE: Playbooks use 'workload:' section for default variables, NOT 'ctx:'
        # The 'ctx' is an internal runtime concept, not a playbook structure
        if playbook.workload:
            self.variables.update(playbook.workload)

        # Merge payload into variables (execution request overrides playbook defaults)
        # NOTE: 'vars' key is REMOVED in strict v10 - use 'ctx' instead
        for k, v in payload.items():
            if k == "ctx" and isinstance(v, dict):
                # Merge execution request ctx into variables (canonical v10)
                self.variables.update(v)
                logger.debug(f"[STATE-INIT] Merged execution ctx into variables: {list(v.keys())}")
            else:
                # Other keys go directly into variables
                self.variables[k] = v

        # Log final state for debugging reconstruction issues
        logger.debug(
            "[STATE-INIT] execution_id=%s variables_count=%s variable_keys=%s",
            execution_id,
            len(self.variables),
            _sample_keys(self.variables),
        )

    

    def to_dict(self) -> dict[str, Any]:
        """Serialize state for persistence in execution.state JSONB.

        CRITICAL: This must stay bounded (<10KB). Only references and scalars
        are persisted. Resolved data (rows, collections) lives in TempStore.
        """
        playbook_metadata = self.playbook.metadata if isinstance(getattr(self.playbook, "metadata", None), dict) else {}

        # Compact step_results: strip any accidentally-resolved data (rows, columns).
        # Keep only {status, reference, context scalars}.
        compact_results = {}
        for step_name, result in self.step_results.items():
            if isinstance(result, dict):
                compact = {
                    k: v for k, v in result.items()
                    if k in ("status", "reference", "context", "row_count", "statement_count")
                    or isinstance(v, (str, int, float, bool)) or v is None
                    or (k == "reference" and isinstance(v, dict))
                    or (k == "context" and isinstance(v, dict))
                }
                compact_results[step_name] = compact
            else:
                compact_results[step_name] = result

        # Compact loop_state: strip collection data, keep only metadata
        compact_loop = {}
        for step_name, ls in self.loop_state.items():
            if isinstance(ls, dict):
                compact_loop[step_name] = {
                    k: v for k, v in ls.items()
                    if k != "collection"  # never serialize full collection
                }
            else:
                compact_loop[step_name] = ls

        # Compact variables: strip step result mirrors (they're in step_results)
        compact_vars = {}
        for k, v in self.variables.items():
            # Keep only playbook workload vars and set mutations (scalars/small dicts)
            # Skip step result mirrors (dicts with 'reference' or 'status' + 'context')
            if isinstance(v, dict) and ("reference" in v or ("status" in v and "context" in v)):
                continue  # step result mirror — skip
            compact_vars[k] = v

        return {
            "execution_id": self.execution_id,
            "catalog_id": self.catalog_id,
            "playbook_path": playbook_metadata.get("path") or playbook_metadata.get("name"),
            "parent_execution_id": self.parent_execution_id,
            "payload": self.payload,
            "current_step": self.current_step,
            "variables": compact_vars,
            "last_event_id": self.last_event_id,
            "step_event_ids": self.step_event_ids,
            "step_results": compact_results,
            "completed_steps": list(self.completed_steps),
            "issued_steps": list(self.issued_steps),
            "failed": self.failed,
            "completed": self.completed,
            "root_event_id": self.root_event_id,
            "loop_state": compact_loop,
            "step_stall_counts": self.step_stall_counts,
            "pagination_state": self.pagination_state,
            "pending_next_actions": self.pending_next_actions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], playbook: Playbook) -> ExecutionState:
        state = cls(
            execution_id=data["execution_id"],
            playbook=playbook,
            payload=data["payload"],
            catalog_id=data["catalog_id"],
            parent_execution_id=data.get("parent_execution_id")
        )
        state.current_step = data.get("current_step")
        state.variables = data.get("variables", {})
        state.last_event_id = data.get("last_event_id")
        state.step_event_ids = data.get("step_event_ids", {})
        state.step_results = data.get("step_results", {})
        state.completed_steps = set(data.get("completed_steps", []))
        state.issued_steps = set(data.get("issued_steps", []))
        state.failed = data.get("failed", False)
        state.completed = data.get("completed", False)
        state.root_event_id = data.get("root_event_id")
        state.loop_state = data.get("loop_state", {})
        state.step_stall_counts = data.get("step_stall_counts", {})
        # emitted_loop_epochs starts empty on each load — DB unique index is authority
        state.emitted_loop_epochs = set()
        state.pagination_state = data.get("pagination_state", {})
        state.pending_next_actions = data.get("pending_next_actions", {})
        return state

    def get_step(self, step_name: str) -> Optional[Step]:
        """Get step by name."""
        for step in self.playbook.workflow:
            if step.step == step_name:
                return step
        return None
    
    def set_current_step(self, step_name: str):
        """Set current executing step."""
        self.current_step = step_name
    
    async def mark_step_completed(self, step_name: str, result: Any = None):
        """Mark step as completed and store a compact reference envelope.

        The state stores ONLY the control-plane envelope (status, reference,
        context scalars) — never resolved row data. Templates that need
        actual data ({{ step.rows }}) resolve on-demand from TempStore via
        LazyStepResult in get_render_context.

        This keeps execution.state bounded at ~5-10KB regardless of how
        many steps/facilities have been processed.
        """
        self.completed_steps.add(step_name)
        if result is not None:
            if isinstance(result, dict):
                # Store ONLY the compact envelope — no eager resolution.
                # Promote context scalars to top level for template access
                # ({{ step.row_count }}, {{ step.status }}) without resolution.
                if "context" not in result:
                    result = {**result, "context": dict(result)}
                context = result.get("context")
                if isinstance(context, dict):
                    promoted = dict(result)
                    for k, v in context.items():
                        # Only promote scalars — NOT lists/dicts (those are data-plane)
                        if isinstance(v, (str, int, float, bool)) or v is None:
                            promoted.setdefault(k, v)
                    result = promoted
            # Store compact envelope in step_results (for TaskResultProxy in render context)
            self.step_results[step_name] = result
            # Do NOT mirror into variables — variables are for playbook workload
            # vars and set mutations only. Step results are accessed via
            # {{ step_name.field }} through TaskResultProxy in get_render_context.

    def get_step_result_ref(self, step_name: str) -> Optional[dict]:
        """Get ResultRef for a step's externalized result, if any.

        Returns the _ref dict if step result was externalized, None otherwise.
        Used for lazy loading of large results via artifact.get.
        """
        result = self.step_results.get(step_name)
        if isinstance(result, dict) and "_ref" in result:
            return result.get("_ref")
        return None

    def is_result_externalized(self, step_name: str) -> bool:
        """Check if a step's result was externalized to remote storage."""
        result = self.step_results.get(step_name)
        return isinstance(result, dict) and "_ref" in result
    
    def is_step_completed(self, step_name: str) -> bool:
        """Check if step is completed."""
        return step_name in self.completed_steps

    def prune_stale_state(self, keep_steps: set[str] | None = None):
        """Evict stale step results and epoch dedup entries to prevent state bloat.

        In long-running multi-facility loops, step_results and variables
        accumulate results from every completed step across ALL facilities.
        The state JSONB grows to 200KB+ and save_state/load_state degrade
        24x over a 10-facility run.

        This prunes:
        - step_results for steps not in keep_steps (default: keep only
          the current step and its immediate neighbors)
        - variables entries that mirror step_results (set by mark_step_completed)
        - emitted_loop_epochs entries (the dedup set grows without bound)

        Called automatically after each loop.done event.
        """
        # Prune step_results: keep only steps that might be referenced
        # by the next transition's templates. In practice, only the
        # current step and its arc targets need their results.
        if keep_steps is None:
            keep_steps = set()
        # Always keep the current step
        if self.current_step:
            keep_steps.add(self.current_step)

        pruned_results = 0
        pruned_vars = 0
        for step_name in list(self.step_results.keys()):
            if step_name not in keep_steps:
                del self.step_results[step_name]
                pruned_results += 1
                # Also prune the mirrored entry in variables
                if step_name in self.variables and not step_name.startswith("_"):
                    del self.variables[step_name]
                    pruned_vars += 1

        # Prune emitted_loop_epochs: keep only entries from the last N epochs
        # to prevent unbounded growth. 50 entries is enough to prevent
        # duplicate emission within a single facility cycle.
        max_epochs = 50
        pruned_epochs = 0
        if len(self.emitted_loop_epochs) > max_epochs:
            sorted_epochs = sorted(self.emitted_loop_epochs)
            to_remove = sorted_epochs[:-max_epochs]
            for e in to_remove:
                self.emitted_loop_epochs.discard(e)
                pruned_epochs += 1

        if pruned_results > 0 or pruned_epochs > 0:
            logger.info(
                "[STATE-PRUNE] Evicted %d step_results, %d variables, %d epochs "
                "(remaining: %d results, %d epochs)",
                pruned_results, pruned_vars, pruned_epochs,
                len(self.step_results), len(self.emitted_loop_epochs),
            )
    
    def init_loop(self, step_name: str, collection: list[Any], iterator: str, mode: str = "sequential", event_id: Optional[int] = None):
        """Initialize loop state for a step.
        
        Args:
            step_name: Name of the step
            collection: Collection to iterate over
            iterator: Iterator variable name
            mode: Iteration mode (sequential or parallel)
            event_id: Event ID that initiated this loop instance (for uniqueness)
        """
        # Evaluate previous invocation for dead-loop detection BEFORE resetting
        if step_name in self.loop_state:
            prev_state = self.loop_state[step_name]
            # Check if previous loop had items but 0 successful completions
            prev_size = len(prev_state.get("collection", []))
            prev_completed = _loop_results_total(prev_state)
            prev_failed = prev_state.get("failed_count", 0)
            prev_break = prev_state.get("break_count", 0)
            successful_slots = prev_completed - prev_failed - prev_break
            
            # If the loop executed fully (or partially), but yielded 0 successful slots
            if prev_size > 0 and prev_completed > 0 and successful_slots <= 0:
                self.step_stall_counts[step_name] = self.step_stall_counts.get(step_name, 0) + 1
                logger.warning(
                    "[DEAD-LOOP-TRACK] Loop %s yielded 0 successful slots on previous run. Stall count: %s",
                    step_name,
                    self.step_stall_counts[step_name]
                )
            else:
                self.step_stall_counts[step_name] = 0

        self.loop_state[step_name] = {
            # Reference-based: store collection_size and collection_ref, NOT the data.
            # The actual collection lives in TempStore (shared cache). Access by index
            # via get_loop_collection + indexing at command creation time.
            "collection_size": len(collection or []) if hasattr(collection, "__len__") else 0,
            "iterator": iterator,
            "index": 0,
            "mode": mode,
            "completed": False,
            "failed_count": 0,
            "break_count": 0,
            "scheduled_count": 0,
            "event_id": event_id,
            "omitted_results_count": 0,  # Number of older results evicted from memory buffer
        }
        logger.debug(f"Initialized loop for step {step_name}: {len(collection or [])} items, mode={mode}, event_id={event_id}")
    
    def get_next_loop_item(self, step_name: str, collection: list = None) -> tuple[Any, int] | None:
        """Get next item from loop. Returns (item, index) or None if done."""
        if step_name not in self.loop_state:
            return None
        
        state = self.loop_state[step_name]
        if state["completed"]:
            return None
        
        index = state["index"]
        collection_size = state.get("collection_size", 0)
        
        if index >= collection_size or (collection is not None and index >= len(collection or [])):
            state["completed"] = True
            return None
        
        item = collection[index] if collection else None
        state["current_item"] = item
        
        state["index"] = index + 1
        state["scheduled_count"] += 1
        return item, index

    def is_loop_done(self, step_name: str) -> bool:
        """Check if loop is completed."""
        if step_name not in self.loop_state:
            return True
        return self.loop_state[step_name]["completed"]
    
    def add_loop_result(self, step_name: str, result: Any, failed: bool = False):
        """Update loop metadata without storing unbounded result arrays."""
        if step_name not in self.loop_state:
            return

        loop_state = self.loop_state[step_name]
        
        # We no longer store an array of results. We only keep a reference to the latest item
        # and standard counters. The full lineage is available via the event table (event_id/parent_event_id).
        loop_state["last_result"] = _compact_loop_result(result)
        loop_state["completed_count"] = loop_state.get("completed_count", 0) + 1
        
        if failed:
            loop_state["failed_count"] += 1
        elif isinstance(result, dict):
            status = str(result.get("status", "")).lower()
            is_policy_break = result.get("policy_break") is True
            if status == "break" or is_policy_break:
                loop_state["break_count"] = loop_state.get("break_count", 0) + 1

    def get_loop_aggregation(self, step_name: str) -> dict[str, Any]:
        """Get aggregated loop results in standard format (counters only, arrays removed)."""
        if step_name not in self.loop_state:
            return {"results": [], "stats": {"total": 0, "success": 0, "failed": 0}}
        
        loop_state = self.loop_state[step_name]
        total = _loop_results_total(loop_state)
        failed = loop_state["failed_count"]
        success = total - failed
        
        return {
            "results": [loop_state.get("last_result")] if loop_state.get("last_result") else [],
            "stats": {
                "total": total,
                "success": success,
                "failed": failed,
            }
        }

    def get_loop_completed_count(self, step_name: str) -> int:
        """Get local loop completion count including omitted buffered entries."""
        if step_name not in self.loop_state:
            return 0
        return _loop_results_total(self.loop_state[step_name])
    
    def add_emitted_loop_epoch(self, step_name: str, event_name: str, loop_event_id: str):
        """Mark a specific transition event as already emitted for deduplication."""
        logger.info(f"[ENGINE-STATE] Marking transition emitted: {step_name}:{event_name}:{loop_event_id}")
        self.emitted_loop_epochs.add(f"{step_name}:{event_name}:{loop_event_id}")

        # On loop.done: prune stale state to prevent unbounded growth.
        # Keep only the current step's results (needed for next arc evaluation).
        if event_name == "loop.done":
            self.prune_stale_state(keep_steps={step_name})

    def get_render_context(self, event: Event) -> dict[str, Any]:
        """Get context for Jinja2 rendering.

        Loop variables are added to state.variables in _create_command_for_step,
        so they will be available via **self.variables spread below.
        """
        logger.debug(
            "ENGINE.get_render_context execution_id=%s catalog_id=%s variables_count=%s variable_keys=%s",
            self.execution_id,
            self.catalog_id,
            len(self.variables),
            _sample_keys(self.variables),
        )

        event_payload = _unwrap_event_payload(event.payload)
        
        # Protected system fields that should not be overridden by workload variables
        protected_fields = {"execution_id", "catalog_id", "job"}
        
        # Separate iteration-scoped variables (loop iterator, loop index)
        iter_vars = {}
        if event.step and event.step in self.loop_state:
            loop_state = self.loop_state[event.step]
            iterator_name = loop_state.get("iterator", "item")
            if iterator_name in self.variables:
                iter_vars[iterator_name] = self.variables[iterator_name]
            iter_vars["_index"] = loop_state["index"] - 1 if loop_state["index"] > 0 else 0
            iter_vars["_first"] = loop_state["index"] == 1
            # Use collection_size if collection is missing (due to persistence optimization)
            collection_size = len(loop_state["collection"]) if "collection" in loop_state else int(loop_state.get("collection_size", 0))
            iter_vars["_last"] = loop_state["index"] >= (collection_size - 1)

        context = {
            "event": {
                "name": event.name,
                "payload": event_payload,
                "step": event.step,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
            },
            # Canonical v10: ctx = execution-scoped, iter = iteration-scoped
            "ctx": self.variables,  # Execution-scoped variables (canonical v10)
            "iter": iter_vars,      # Iteration-scoped variables (canonical v10)
            # Backward compatibility: workload namespace for {{ workload.xxx }}
            "workload": self.variables,  # Legacy alias for Core playbooks
        }

        # Step results are accessed via {{ step_name.field }} through TaskResultProxy.
        # Only inject compact reference envelopes — resolution happens on-demand
        # in TaskResultProxy.__getattr__ from shared cache (TempStore).
        # This keeps the render context bounded regardless of step count.
        for step_name, step_result in self.step_results.items():
            if step_name not in context and step_name not in protected_fields:
                context[step_name] = step_result

        # Add variables to context only if they don't collide with reserved keys
        for k, v in self.variables.items():
            if k not in context and k not in protected_fields:
                context[k] = v
        
        # Set protected fields AFTER spreading variables to ensure they are not overridden
        # CRITICAL: Convert IDs to strings to prevent JavaScript precision loss with Snowflake IDs
        context["execution_id"] = str(self.execution_id) if self.execution_id else None
        context["catalog_id"] = str(self.catalog_id) if self.catalog_id else None
        context["job"] = {
            "uuid": str(self.execution_id) if self.execution_id else None,
            "execution_id": str(self.execution_id) if self.execution_id else None,
            "id": str(self.execution_id) if self.execution_id else None
        }
        
        # Add loop metadata context if step has active loop
        if event.step and event.step in self.loop_state:
            loop_state = self.loop_state[event.step]
            context["loop"] = {
                "index": loop_state["index"] - 1 if loop_state["index"] > 0 else 0,  # Current item index
                "first": loop_state["index"] == 1,
                "length": loop_state.get("collection_size", 0),
                "done": loop_state["completed"]
            }
            # Note: Iterator variable itself (e.g., {{ num }}) comes from state.variables
        
        # Add event-specific data (strict reference-only contract).
        if isinstance(event_payload, dict):
            step_result = self.step_results.get(event.step) if event.step else None
            if step_result is None and isinstance(event.step, str) and event.step.endswith(":task_sequence"):
                step_result = self.step_results.get(event.step.rsplit(":", 1)[0])

            output_view = _build_output_view(
                event_payload=event_payload,
                step_result=step_result,
            )
            context["output"] = output_view
            if output_view.get("error") is not None:
                context["error"] = output_view.get("error")

        return context
