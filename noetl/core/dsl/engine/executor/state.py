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
        return {
            "execution_id": self.execution_id,
            "catalog_id": self.catalog_id,
            "parent_execution_id": self.parent_execution_id,
            "payload": self.payload,
            "current_step": self.current_step,
            "variables": self.variables,
            "last_event_id": self.last_event_id,
            "step_event_ids": self.step_event_ids,
            "step_results": self.step_results,
            "completed_steps": list(self.completed_steps),
            "issued_steps": list(self.issued_steps),
            "failed": self.failed,
            "completed": self.completed,
            "root_event_id": self.root_event_id,
            "loop_state": self.loop_state,
            "step_stall_counts": self.step_stall_counts,
            "emitted_loop_epochs": list(self.emitted_loop_epochs),
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
        state.emitted_loop_epochs = set(data.get("emitted_loop_epochs", []))
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
    
    def mark_step_completed(self, step_name: str, result: Any = None):
        """Mark step as completed and store result in memory and transient.

        If result contains _ref (externalized via ResultRef pattern), the extracted
        output_select fields are stored directly for template access:
        - {{ step_name.status }} accesses extracted field
        - {{ step_name._ref }} accesses the ResultRef for lazy loading
        """
        self.completed_steps.add(step_name)
        if result is not None:
            self.step_results[step_name] = result
            self.variables[step_name] = result

            # Log if result was externalized
            if isinstance(result, dict) and "_ref" in result:
                logger.info(
                    f"[STATE] Step {step_name}: externalized result stored | "
                    f"extracted_fields={[k for k in result.keys() if not k.startswith('_')]}"
                )
            # Also persist to transient for rendering in subsequent steps
            # This is done async in the engine after calling mark_step_completed

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
            # Keep a local snapshot so downstream in-place list mutations outside loop_state
            # do not alter continuation/retry scheduling.
            "collection": list(collection),
            "iterator": iterator,
            "index": 0,
            "mode": mode,
            "completed": False,
            "results": [],  # Track iteration results for aggregation
            "failed_count": 0,  # Track failed iterations
            "break_count": 0,  # Track skipped/break iterations
            "scheduled_count": 0,  # Track issued iterations for max_in_flight gating
            "event_id": event_id,  # Track which event initiated this loop instance
            "omitted_results_count": 0,  # Number of older results evicted from memory buffer
        }
        logger.debug(f"Initialized loop for step {step_name}: {len(collection)} items, mode={mode}, event_id={event_id}")
    
    def get_next_loop_item(self, step_name: str) -> tuple[Any, int] | None:
        """Get next item from loop. Returns (item, index) or None if done."""
        if step_name not in self.loop_state:
            return None
        
        state = self.loop_state[step_name]
        if state["completed"]:
            return None
        
        collection = state["collection"]
        index = state["index"]
        
        if index >= len(collection):
            state["completed"] = True
            return None
        
        item = collection[index]
        state["index"] = index + 1
        return (item, index)
    
    def is_loop_done(self, step_name: str) -> bool:
        """Check if loop is completed."""
        if step_name not in self.loop_state:
            return True
        return self.loop_state[step_name]["completed"]
    
    def add_loop_result(self, step_name: str, result: Any, failed: bool = False):
        """Add iteration result to loop aggregation (local cache only)."""
        if step_name not in self.loop_state:
            return

        stored_result = _compact_loop_result(result)
        loop_state = self.loop_state[step_name]
        results_buffer = loop_state.get("results", [])
        if not isinstance(results_buffer, list):
            results_buffer = []
        results_buffer.append(stored_result)
        retained_results, omitted_count = _retain_recent_loop_results(
            results_buffer,
            int(loop_state.get("omitted_results_count", 0) or 0),
        )
        loop_state["results"] = retained_results
        loop_state["omitted_results_count"] = omitted_count
        if failed:
            loop_state["failed_count"] += 1
        elif isinstance(result, dict):
            status = str(result.get("status", "")).lower()
            is_policy_break = result.get("policy_break") is True
            if status == "break" or is_policy_break:
                loop_state["break_count"] = loop_state.get("break_count", 0) + 1

        if stored_result is not result:
            logger.info(
                "[LOOP] Compacted large iteration result for %s (max=%s bytes)",
                step_name,
                _LOOP_RESULT_MAX_BYTES,
            )
        logger.debug(
            "Added iteration result to loop %s: total=%s buffered=%s omitted=%s",
            step_name,
            _loop_results_total(loop_state),
            len(loop_state.get("results", [])),
            loop_state.get("omitted_results_count", 0),
        )
        
        # Note: Distributed sync to NATS K/V happens in engine.handle_event()
    
    def get_loop_aggregation(self, step_name: str) -> dict[str, Any]:
        """Get aggregated loop results in standard format."""
        if step_name not in self.loop_state:
            return {"results": [], "stats": {"total": 0, "success": 0, "failed": 0}}
        
        loop_state = self.loop_state[step_name]
        omitted_results = int(loop_state.get("omitted_results_count", 0) or 0)
        buffered_results = loop_state.get("results", [])
        if not isinstance(buffered_results, list):
            buffered_results = []
        total = _loop_results_total(loop_state)
        failed = loop_state["failed_count"]
        success = total - failed
        
        return {
            "results": buffered_results,
            "stats": {
                "total": total,
                "success": success,
                "failed": failed
            },
            "omitted_results_count": omitted_results,
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
            **self.step_results,  # Make step results accessible (e.g., {{ process }})
        }
        
        # Add variables to context only if they don't collide with reserved keys
        # This provides a flatter namespace while protecting system fields
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
                "length": len(loop_state["collection"]),
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


