"""
NATS K/V cache for distributed execution state.

Replaces in-memory cache with distributed NATS JetStream K/V store
to enable horizontal scaling of server pods.

IMPORTANT: NATS K/V has a 1MB max value size limit. This module stores ONLY:
- Loop metadata (collection_size, iterator, mode)
- Completion counts (completed_count integer)
- Pointers/references (event_id, execution_id)

NEVER store actual result values in NATS K/V - they are stored in the
event table and retrieved via the aggregate service when needed.
"""

import json
import asyncio
import random
import re
from typing import Any, Optional
from datetime import datetime, timezone
import nats
from nats.js import JetStreamContext
from nats.js.kv import KeyValue
from nats.js.errors import KeyNotFoundError
from noetl.core.logger import setup_logger
from noetl.core.config import get_settings

# NATS KV valid key characters: alphanumeric, hyphen, forward slash, underscore, equals, dot
_NATS_KEY_INVALID_RE = re.compile(r"[^-/_=.a-zA-Z0-9]")

logger = setup_logger(__name__, include_location=True)
settings = get_settings()


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso_utc(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        normalized = value
        if normalized.endswith("Z"):
            normalized = f"{normalized[:-1]}+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


class NATSKVCache:
    """NATS K/V cache client for execution state."""
    
    def __init__(self):
        self._nc: Optional[nats.NATS] = None
        self._js: Optional[JetStreamContext] = None
        self._kv: Optional[KeyValue] = None
        self._bucket_name = "noetl_execution_state"
        self._lock = asyncio.Lock()
    
    async def connect(self, nats_url: Optional[str] = None):
        """Connect to NATS and create/get K/V bucket."""
        async with self._lock:
            if self._nc is not None:
                return  # Already connected
            
            try:
                # Use settings from config.py
                url = nats_url or settings.nats_url
                user = settings.nats_user
                password = settings.nats_password
                
                self._nc = await nats.connect(
                    servers=[url],
                    user=user,
                    password=password,
                    name="noetl_kv_cache"
                )
                self._js = self._nc.jetstream()
                
                # Create or get K/V bucket with TTL
                try:
                    self._kv = await self._js.create_key_value(
                        bucket=self._bucket_name,
                        description="NoETL execution state cache",
                        ttl=86400,  # 24 hour TTL (long-running jobs may batch across hours)
                        max_value_size=1024 * 1024,  # 1MB max value
                        history=5,  # Keep 5 versions
                    )
                    logger.debug(f"Created NATS K/V bucket: {self._bucket_name}")
                except Exception as e:
                    # Bucket might already exist
                    self._kv = await self._js.key_value(self._bucket_name)
                    logger.info(f"Connected to existing NATS K/V bucket: {self._bucket_name}")
                
                logger.info(f"NATS K/V cache connected to {url} (user: {user})")
                
            except Exception as e:
                logger.error(f"Failed to connect to NATS K/V: {e}")
                raise
    
    async def close(self):
        """Close NATS connection."""
        if self._nc:
            await self._nc.close()
            self._nc = None
            self._js = None
            self._kv = None
    
    def _make_key(self, execution_id: str, key_type: str) -> str:
        """Create namespaced key for execution state.

        NATS K/V valid characters: [-/_=.a-zA-Z0-9].  Keys must not start or
        end with '.'.  Format: exec.{execution_id}.{key_type}
        """
        # Replace colons with dots (primary separator conversion), then
        # replace any remaining invalid character with '_'.
        safe_exec_id = _NATS_KEY_INVALID_RE.sub("_", str(execution_id).replace(":", "."))
        safe_key_type = _NATS_KEY_INVALID_RE.sub("_", str(key_type).replace(":", "."))
        # Strip leading/trailing dots so the composite key is always valid.
        safe_exec_id = safe_exec_id.strip(".")
        safe_key_type = safe_key_type.strip(".")
        return f"exec.{safe_exec_id}.{safe_key_type}"

    async def get_loop_collection(self, execution_id: str, step_name: str, loop_event_id: str) -> Optional[list]:
        """Retrieve rendered loop collection from NATS KV."""
        if not self._kv:
            await self.connect()
        key = self._make_key(execution_id, f"loop_coll:{step_name}:{loop_event_id}")
        try:
            entry = await self._kv.get(key)
            if entry and entry.value:
                return json.loads(entry.value.decode("utf-8"))
        except KeyNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"[NATS-KV] Failed to get loop collection: {e}")
        return None

    async def save_loop_collection(self, execution_id: str, step_name: str, loop_event_id: str, collection: list):
        """Save rendered loop collection to NATS KV."""
        if not self._kv:
            await self.connect()
        key = self._make_key(execution_id, f"loop_coll:{step_name}:{loop_event_id}")
        try:
            data = json.dumps(collection).encode("utf-8")
            await self._kv.put(key, data)
            logger.debug(f"[NATS-KV] Saved loop collection for {step_name} (size={len(data)} bytes)")
        except Exception as e:
            logger.warning(f"[NATS-KV] Failed to save loop collection: {e}")

    async def add_loop_result(
        self, execution_id: str, step_name: str, event_id: str, result: dict, failed: bool = False
    ):
        """Atomically add an iteration result to the NATS KV loop state."""
        if not self._kv:
            await self.connect()

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        max_retries = 10
        for attempt in range(max_retries):
            try:
                entry = await self._kv.get(key)
                if not entry:
                    # Initialize if missing
                    state = {
                        "completed_count": 0,
                        "scheduled_count": 0,
                        "collection_size": 0,
                        "results": [],
                        "failed_count": 0,
                        "updated_at": _utcnow_iso()
                    }
                    revision = None
                else:
                    state = json.loads(entry.value.decode("utf-8"))
                    revision = entry.revision

                # Append result
                results = state.get("results", [])
                results.append(result)
                state["results"] = results
                
                if failed:
                    state["failed_count"] = int(state.get("failed_count", 0)) + 1
                    
                state["updated_at"] = _utcnow_iso()

                value = json.dumps(state).encode("utf-8")
                
                if revision is None:
                    await self._kv.put(key, value)
                    return
                else:
                    await self._kv.update(key, value, last=revision)
                    return
            except Exception as e:
                # KeyWrongLastSequenceError triggers retry
                if attempt == max_retries - 1:
                    logger.warning(f"Failed to add loop result to NATS KV after {max_retries} attempts: {e}")
                    raise

    async def get_loop_state(self, execution_id: str, step_name: str, event_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        """Get loop state for a specific step instance.
        
        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            event_id: Event ID that initiated this step instance (for uniqueness)
        """
        if not self._kv:
            await self.connect()
        
        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)
        try:
            entry = await self._kv.get(key)
            if entry and entry.value:
                return json.loads(entry.value.decode('utf-8'))
            return None
        except KeyNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Failed to get loop state from NATS K/V: {e}")
            return None
    
    async def set_loop_state(self, execution_id: str, step_name: str, state: dict[str, Any], event_id: Optional[str] = None) -> bool:
        """Set loop state for a specific step instance.

        IMPORTANT: state should contain only metadata and counts, NOT result values:
        - collection_size: int - number of items in the loop collection
        - completed_count: int - number of completed iterations
        - scheduled_count: int - number of claimed/issued iterations
        - iterator: str - iterator variable name
        - mode: str - sequential or parallel
        - event_id: str - event ID that initiated this loop

        NEVER include 'results' array with actual values - those belong in the event table.

        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            state: Loop state dictionary (metadata only, no result values)
            event_id: Event ID that initiated this step instance (for uniqueness)
        """
        if not self._kv:
            await self.connect()
        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        max_retries = 10
        for attempt in range(max_retries):
            try:
                try:
                    entry = await self._kv.get(key)
                except KeyNotFoundError:
                    entry = None

                existing_state = (
                    json.loads(entry.value.decode("utf-8"))
                    if entry and entry.value
                    else {}
                )

                incoming_state = dict(state)

                # Safety check: warn and strip results if accidentally included.
                if "results" in incoming_state:
                    logger.warning(
                        f"[NATS-KV] Stripping 'results' array from loop state for {step_name} - use completed_count instead"
                    )
                    incoming_state = {
                        k: v for k, v in incoming_state.items() if k != "results"
                    }

                incoming_completed = int(incoming_state.get("completed_count", 0) or 0)
                incoming_scheduled = int(
                    incoming_state.get("scheduled_count", incoming_completed) or incoming_completed
                )
                if incoming_scheduled < incoming_completed:
                    incoming_scheduled = incoming_completed

                existing_completed = int(existing_state.get("completed_count", 0) or 0)
                existing_scheduled = int(
                    existing_state.get("scheduled_count", existing_completed) or existing_completed
                )
                if existing_scheduled < existing_completed:
                    existing_scheduled = existing_completed

                incoming_collection_size = int(incoming_state.get("collection_size", 0) or 0)
                existing_collection_size = int(existing_state.get("collection_size", 0) or 0)
                safe_collection_size = max(incoming_collection_size, existing_collection_size)

                payload = dict(existing_state)
                payload.update(incoming_state)
                payload["completed_count"] = max(existing_completed, incoming_completed)
                payload["scheduled_count"] = max(
                    existing_scheduled,
                    incoming_scheduled,
                    payload["completed_count"],
                )
                payload["collection_size"] = safe_collection_size

                # Preserve one-way completion guards once claimed.
                if existing_state.get("loop_done_claimed"):
                    payload["loop_done_claimed"] = True
                    payload.setdefault(
                        "loop_done_claimed_at",
                        existing_state.get("loop_done_claimed_at"),
                    )

                # Epoch-scoped loop metadata must never exceed the loop's collection size.
                if safe_collection_size > 0:
                    if payload["completed_count"] > safe_collection_size:
                        payload["completed_count"] = safe_collection_size
                    if payload["scheduled_count"] > safe_collection_size:
                        payload["scheduled_count"] = safe_collection_size
                    if payload["scheduled_count"] < payload["completed_count"]:
                        payload["scheduled_count"] = payload["completed_count"]

                payload["updated_at"] = _utcnow_iso()
                value = json.dumps(payload).encode("utf-8")
                if entry is None:
                    await self._kv.put(key, value)
                else:
                    await self._kv.update(key, value, last=entry.revision)
                logger.debug(f"Stored loop state in NATS K/V: {key}")
                return True
            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < max_retries - 1:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.error(f"Failed to set loop state in NATS K/V: {e}")
                return False

        return False

    async def get_execution_state(self, execution_id: str) -> Optional[dict[str, Any]]:
        """Get execution supervisor state."""
        if not self._kv:
            await self.connect()

        key = self._make_key(execution_id, "execution")
        try:
            entry = await self._kv.get(key)
            if entry and entry.value:
                return json.loads(entry.value.decode("utf-8"))
            return None
        except KeyNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Failed to get execution supervisor state from NATS K/V: {e}")
            return None

    async def set_execution_state(self, execution_id: str, state: dict[str, Any]) -> bool:
        """Set execution supervisor state."""
        if not self._kv:
            await self.connect()

        key = self._make_key(execution_id, "execution")
        payload = dict(state)
        payload["updated_at"] = _utcnow_iso()
        try:
            value = json.dumps(payload).encode("utf-8")
            await self._kv.put(key, value)
            return True
        except Exception as e:
            logger.warning(f"Failed to set execution supervisor state in NATS K/V: {e}")
            return False

    async def get_pending_command_count(self, execution_id: str) -> Optional[int]:
        """Get pending command count from execution supervisor state."""
        state = await self.get_execution_state(execution_id)
        if state is None:
            return None
        return int(state.get("pending_command_count", 0) or 0)

    async def register_command_issued(
        self,
        execution_id: str,
        command_id: str,
        step_name: str,
        *,
        command_event_id: Optional[int] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Register an issued command in the supervisor and increment pending count once."""
        if not command_id:
            return False
        if not self._kv:
            await self.connect()

        command_key = self._make_key(execution_id, f"command:{command_id}")
        execution_key = self._make_key(execution_id, "execution")
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}

        for attempt in range(10):
            try:
                existing_command = None
                existing_command_revision = None
                try:
                    command_entry = await self._kv.get(command_key)
                    if command_entry and command_entry.value:
                        existing_command = json.loads(command_entry.value.decode("utf-8"))
                        existing_command_revision = command_entry.revision
                except KeyNotFoundError:
                    existing_command = None

                if existing_command and str(existing_command.get("status") or "").upper() not in terminal_statuses:
                    return True

                existing_execution = None
                execution_revision = None
                try:
                    execution_entry = await self._kv.get(execution_key)
                    if execution_entry and execution_entry.value:
                        existing_execution = json.loads(execution_entry.value.decode("utf-8"))
                        execution_revision = execution_entry.revision
                except KeyNotFoundError:
                    existing_execution = None

                now_iso = _utcnow_iso()
                command_state = dict(existing_command or {})
                command_state.update(
                    {
                        "command_id": str(command_id),
                        "execution_id": str(execution_id),
                        "step_name": str(step_name),
                        "status": "ISSUED",
                        "command_event_id": command_event_id,
                        "issued_at": command_state.get("issued_at") or now_iso,
                        "updated_at": now_iso,
                    }
                )
                if meta:
                    command_state["meta"] = dict(meta)

                execution_state = dict(existing_execution or {})
                pending_count = int(execution_state.get("pending_command_count", 0) or 0)
                if existing_command is None:
                    pending_count += 1
                execution_state.update(
                    {
                        "execution_id": str(execution_id),
                        "pending_command_count": max(0, pending_count),
                        "last_command_id": str(command_id),
                        "last_command_step": str(step_name),
                        "updated_at": now_iso,
                    }
                )

                command_value = json.dumps(command_state).encode("utf-8")
                execution_value = json.dumps(execution_state).encode("utf-8")

                if existing_command_revision is None:
                    await self._kv.put(command_key, command_value)
                else:
                    await self._kv.update(command_key, command_value, last=existing_command_revision)

                if execution_revision is None:
                    await self._kv.put(execution_key, execution_value)
                else:
                    await self._kv.update(execution_key, execution_value, last=execution_revision)

                return True
            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < 9:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.warning(
                    "Failed to register command issue in NATS K/V for execution=%s command_id=%s: %s",
                    execution_id,
                    command_id,
                    e,
                )
                return False

        return False

    async def mark_command_terminal(
        self,
        execution_id: str,
        command_id: str,
        status: str,
        *,
        event_name: Optional[str] = None,
        event_id: Optional[int] = None,
        step_name: Optional[str] = None,
    ) -> bool:
        """Mark a command terminal and decrement pending count once."""
        if not command_id:
            return False
        if not self._kv:
            await self.connect()

        command_key = self._make_key(execution_id, f"command:{command_id}")
        execution_key = self._make_key(execution_id, "execution")
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
        normalized_status = str(status or "").upper() or "COMPLETED"

        for attempt in range(10):
            try:
                try:
                    command_entry = await self._kv.get(command_key)
                except KeyNotFoundError:
                    command_entry = None
                try:
                    execution_entry = await self._kv.get(execution_key)
                except KeyNotFoundError:
                    execution_entry = None

                existing_command = (
                    json.loads(command_entry.value.decode("utf-8"))
                    if command_entry and command_entry.value
                    else {}
                )
                existing_execution = (
                    json.loads(execution_entry.value.decode("utf-8"))
                    if execution_entry and execution_entry.value
                    else {}
                )
                prior_status = str(existing_command.get("status") or "").upper()
                if prior_status in terminal_statuses:
                    return True

                now_iso = _utcnow_iso()
                command_state = dict(existing_command)
                command_state.update(
                    {
                        "command_id": str(command_id),
                        "execution_id": str(execution_id),
                        "step_name": str(step_name or existing_command.get("step_name") or ""),
                        "status": normalized_status,
                        "terminal_event_name": event_name,
                        "terminal_event_id": event_id,
                        "terminal_at": now_iso,
                        "updated_at": now_iso,
                    }
                )

                execution_state = dict(existing_execution)
                pending_count = int(execution_state.get("pending_command_count", 0) or 0)
                if prior_status not in terminal_statuses and pending_count > 0:
                    pending_count -= 1
                execution_state.update(
                    {
                        "execution_id": str(execution_id),
                        "pending_command_count": max(0, pending_count),
                        "last_terminal_command_id": str(command_id),
                        "last_terminal_event_name": event_name,
                        "updated_at": now_iso,
                    }
                )

                command_value = json.dumps(command_state).encode("utf-8")
                execution_value = json.dumps(execution_state).encode("utf-8")
                if command_entry is None:
                    await self._kv.put(command_key, command_value)
                else:
                    await self._kv.update(command_key, command_value, last=command_entry.revision)

                if execution_entry is None:
                    await self._kv.put(execution_key, execution_value)
                else:
                    await self._kv.update(execution_key, execution_value, last=execution_entry.revision)
                return True
            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < 9:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.warning(
                    "Failed to mark command terminal in NATS K/V for execution=%s command_id=%s: %s",
                    execution_id,
                    command_id,
                    e,
                )
                return False

        return False

    async def get_loop_iteration_state(
        self,
        execution_id: str,
        step_name: str,
        iteration_index: int,
        *,
        event_id: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Get per-iteration supervisor state for a loop item."""
        if not self._kv:
            await self.connect()

        key_suffix = f"loop-item:{step_name}:{event_id}:{int(iteration_index)}" if event_id else f"loop-item:{step_name}:{int(iteration_index)}"
        key = self._make_key(execution_id, key_suffix)
        try:
            entry = await self._kv.get(key)
            if entry and entry.value:
                return json.loads(entry.value.decode("utf-8"))
            return None
        except KeyNotFoundError:
            return None
        except Exception as e:
            logger.warning(f"Failed to get loop iteration state from NATS K/V: {e}")
            return None

    async def set_loop_iteration_state(
        self,
        execution_id: str,
        step_name: str,
        iteration_index: int,
        state: dict[str, Any],
        *,
        event_id: Optional[str] = None,
    ) -> bool:
        """Persist per-iteration supervisor state for a loop item."""
        if not self._kv:
            await self.connect()

        key_suffix = f"loop-item:{step_name}:{event_id}:{int(iteration_index)}" if event_id else f"loop-item:{step_name}:{int(iteration_index)}"
        key = self._make_key(execution_id, key_suffix)
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}

        for attempt in range(10):
            try:
                try:
                    entry = await self._kv.get(key)
                except KeyNotFoundError:
                    entry = None

                existing = (
                    json.loads(entry.value.decode("utf-8"))
                    if entry and entry.value
                    else {}
                )

                payload = dict(existing)
                payload.update(state)

                existing_status = str(existing.get("status") or "").upper()
                incoming_status = str(state.get("status") or "").upper()
                if existing_status in terminal_statuses and incoming_status not in terminal_statuses:
                    payload["status"] = existing_status
                    for terminal_key in (
                        "terminal_at",
                        "terminal_event_name",
                        "terminal_event_id",
                    ):
                        if terminal_key in existing and terminal_key not in state:
                            payload[terminal_key] = existing[terminal_key]

                payload["execution_id"] = str(execution_id)
                payload["step_name"] = str(step_name)
                payload["iteration_index"] = int(iteration_index)
                if event_id is not None:
                    payload["loop_event_id"] = str(event_id)
                payload["updated_at"] = _utcnow_iso()

                value = json.dumps(payload).encode("utf-8")
                if entry is None:
                    await self._kv.put(key, value)
                else:
                    await self._kv.update(key, value, last=entry.revision)
                return True
            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < 9:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.warning(f"Failed to set loop iteration state in NATS K/V: {e}")
                return False

        return False

    async def _list_loop_iteration_payloads(
        self,
        execution_id: str,
        step_name: str,
        *,
        event_id: Optional[str] = None,
    ) -> Optional[list[dict[str, Any]]]:
        """Enumerate loop-item supervisor payloads for a specific epoch."""
        if not self._kv:
            await self.connect()

        key_suffix = (
            f"loop-item:{step_name}:{event_id}:"
            if event_id
            else f"loop-item:{step_name}:"
        )
        prefix = self._make_key(execution_id, key_suffix)

        try:
            keys = await self._kv.keys()
        except Exception as e:
            logger.warning(
                "Failed to enumerate loop iteration state keys in NATS K/V for execution=%s "
                "step=%s event_id=%s: %s",
                execution_id,
                step_name,
                event_id,
                e,
            )
            return None

        payloads: list[dict[str, Any]] = []
        for key in keys or []:
            if not str(key).startswith(prefix):
                continue
            try:
                entry = await self._kv.get(key)
            except KeyNotFoundError:
                continue
            except Exception as e:
                logger.warning(
                    "Failed to fetch loop iteration state from NATS K/V for key=%s: %s",
                    key,
                    e,
                )
                continue

            if not entry or not entry.value:
                continue

            try:
                payload = json.loads(entry.value.decode("utf-8"))
            except Exception:
                continue
            payloads.append(payload)

        return payloads

    async def mark_loop_iteration_terminal(
        self,
        execution_id: str,
        step_name: str,
        iteration_index: int,
        *,
        event_id: Optional[str] = None,
        command_id: Optional[str] = None,
        status: str = "COMPLETED",
        result_pointer: Optional[dict[str, Any]] = None,
        terminal_event_name: Optional[str] = None,
        terminal_event_id: Optional[int] = None,
    ) -> bool:
        """Mark a loop item terminal and persist an optional result pointer."""
        payload: dict[str, Any] = {
            "status": str(status or "").upper() or "COMPLETED",
            "terminal_event_name": terminal_event_name,
            "terminal_event_id": terminal_event_id,
            "terminal_at": _utcnow_iso(),
        }
        if command_id:
            payload["command_id"] = str(command_id)
        if result_pointer:
            payload["result_pointer"] = dict(result_pointer)
        return await self.set_loop_iteration_state(
            execution_id,
            step_name,
            iteration_index,
            payload,
            event_id=event_id,
        )

    async def count_observed_loop_iteration_terminals(
        self,
        execution_id: str,
        step_name: str,
        *,
        event_id: Optional[str] = None,
    ) -> int:
        """Count loop items with a supervised terminal signal for an epoch."""
        if not self._kv:
            await self.connect()
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
        terminal_event_names = {"call.done", "call.error"}

        payloads = await self._list_loop_iteration_payloads(
            execution_id,
            step_name,
            event_id=event_id,
        )
        if payloads is None:
            return -1

        observed_count = 0
        for payload in payloads:
            status = str(payload.get("status") or "").upper()
            last_event_name = str(payload.get("last_event_name") or "").lower()
            if status in terminal_statuses or last_event_name in terminal_event_names:
                observed_count += 1

        return observed_count

    async def find_supervisor_missing_loop_iteration_indices(
        self,
        execution_id: str,
        step_name: str,
        *,
        event_id: Optional[str] = None,
        limit: int = 10,
        min_age_seconds: float = 0.0,
    ) -> Optional[list[int]]:
        """Find issued loop items with no observed start/terminal signal."""
        if limit <= 0:
            return []

        payloads = await self._list_loop_iteration_payloads(
            execution_id,
            step_name,
            event_id=event_id,
        )
        if payloads is None:
            return None

        now_utc = datetime.now(timezone.utc)
        threshold = max(0.0, float(min_age_seconds or 0.0))
        candidates: list[int] = []
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
        terminal_event_names = {"call.done", "call.error"}

        for payload in payloads:
            iteration_index = payload.get("iteration_index")
            if iteration_index is None:
                continue

            status = str(payload.get("status") or "").upper()
            last_event_name = str(payload.get("last_event_name") or "").lower()
            if status in terminal_statuses or last_event_name in terminal_event_names:
                continue
            if status == "STARTED" or last_event_name == "command.started" or payload.get("started_at"):
                continue

            issued_at = (
                _parse_iso_utc(payload.get("issued_at"))
                or _parse_iso_utc(payload.get("claimed_at"))
                or _parse_iso_utc(payload.get("updated_at"))
            )
            if issued_at is None:
                continue
            if (now_utc - issued_at).total_seconds() < threshold:
                continue

            try:
                candidates.append(int(iteration_index))
            except Exception:
                continue

        candidates.sort()
        return candidates[:limit]

    async def find_supervisor_orphaned_loop_iteration_indices(
        self,
        execution_id: str,
        step_name: str,
        *,
        event_id: Optional[str] = None,
        limit: int = 10,
    ) -> Optional[list[int]]:
        """Find loop items that appear issued/claimed but never started or terminated."""
        return await self.find_supervisor_missing_loop_iteration_indices(
            execution_id,
            step_name,
            event_id=event_id,
            limit=limit,
            min_age_seconds=0.0,
        )

    async def try_record_loop_iteration_terminal(
        self,
        execution_id: str,
        step_name: str,
        iteration_index: int,
        *,
        event_id: Optional[str] = None,
        command_id: Optional[str] = None,
        status: str = "COMPLETED",
        terminal_event_name: Optional[str] = None,
        terminal_event_id: Optional[int] = None,
    ) -> Optional[bool]:
        """Attempt to mark a loop item terminal exactly once.

        Returns:
            True if this call transitioned the loop item to terminal.
            False if the loop item was already terminal.
            None if the loop epoch state does not exist.
        """
        if not self._kv:
            await self.connect()

        loop_state = await self.get_loop_state(
            execution_id,
            step_name,
            event_id=event_id,
        )
        if loop_state is None:
            return None

        key_suffix = (
            f"loop-item:{step_name}:{event_id}:{int(iteration_index)}"
            if event_id
            else f"loop-item:{step_name}:{int(iteration_index)}"
        )
        key = self._make_key(execution_id, key_suffix)
        terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}

        for attempt in range(10):
            try:
                try:
                    entry = await self._kv.get(key)
                except KeyNotFoundError:
                    entry = None

                existing_state = (
                    json.loads(entry.value.decode("utf-8"))
                    if entry and entry.value
                    else {}
                )
                prior_status = str(existing_state.get("status") or "").upper()
                if prior_status in terminal_statuses:
                    return False

                now_iso = _utcnow_iso()
                payload = dict(existing_state)
                payload.update(
                    {
                        "execution_id": str(execution_id),
                        "step_name": str(step_name),
                        "iteration_index": int(iteration_index),
                        "status": str(status or "").upper() or "COMPLETED",
                        "terminal_event_name": terminal_event_name,
                        "terminal_event_id": terminal_event_id,
                        "terminal_at": now_iso,
                        "updated_at": now_iso,
                    }
                )
                if event_id is not None:
                    payload["loop_event_id"] = str(event_id)
                if command_id:
                    payload["command_id"] = str(command_id)

                value = json.dumps(payload).encode("utf-8")
                if entry is None:
                    await self._kv.put(key, value)
                else:
                    await self._kv.update(key, value, last=entry.revision)
                return True
            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < 9:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.warning(
                    "Failed to record loop iteration terminal state in NATS K/V for execution=%s "
                    "step=%s iteration=%s event_id=%s: %s",
                    execution_id,
                    step_name,
                    iteration_index,
                    event_id,
                    e,
                )
                return None

        return None
    
    async def increment_loop_completed(self, execution_id: str, step_name: str, event_id: Optional[str] = None) -> int:
        """Atomically increment the completed_count for a loop.

        This replaces the old append_loop_result which stored actual results.
        NATS K/V now only tracks the count of completed iterations - actual
        results are stored in the event table and fetched via aggregate service.

        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            event_id: Event ID that initiated this step instance (for uniqueness)

        Returns:
            The new completed_count value, or -1 on failure
        """
        if not self._kv:
            await self.connect()

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        # Read-modify-write with retry logic (optimistic locking).
        # High-concurrency parallel loops can generate dozens of concurrent increments;
        # keep retry budget high to avoid dropping completion signals.
        max_retries = 50
        for attempt in range(max_retries):
            try:
                # Get current state
                entry = await self._kv.get(key)
                if not entry:
                    logger.warning(f"Loop state not found for {step_name}, cannot increment count")
                    return -1

                state = json.loads(entry.value.decode('utf-8'))

                # Increment completed count
                current_count = state.get("completed_count", 0)
                state["completed_count"] = current_count + 1
                scheduled_count = int(state.get("scheduled_count", state["completed_count"]) or state["completed_count"])
                if scheduled_count < state["completed_count"]:
                    scheduled_count = state["completed_count"]
                state["scheduled_count"] = scheduled_count
                now_iso = _utcnow_iso()
                state["last_completed_at"] = now_iso
                state["last_progress_at"] = now_iso
                state["updated_at"] = now_iso

                # Update with revision check (optimistic locking)
                value = json.dumps(state).encode('utf-8')
                await self._kv.update(key, value, last=entry.revision)

                logger.debug(f"Incremented loop completed count: {key}, completed_count={state['completed_count']}")
                return state["completed_count"]

            except Exception as e:
                err = str(e).lower()
                if "wrong last sequence" in err and attempt < max_retries - 1:
                    # Concurrent update, retry with jittered exponential backoff.
                    base = min(0.002 * (2 ** min(attempt, 7)), 0.2)
                    sleep_seconds = base * (0.5 + random.random())
                    await asyncio.sleep(sleep_seconds)
                    continue
                if "wrong last sequence" in err:
                    logger.warning(
                        "Failed to increment loop completed count after %s optimistic retries "
                        "(execution=%s step=%s event_id=%s)",
                        max_retries,
                        execution_id,
                        step_name,
                        event_id,
                    )
                else:
                    logger.error(f"Failed to increment loop completed count: {e}")
                return -1

        return -1

    async def try_claim_loop_done(
        self,
        execution_id: str,
        step_name: str,
        event_id: Optional[str] = None,
    ) -> bool:
        """Atomically claim the right to fire loop.done for this loop epoch.

        Uses compare-and-swap on NATS K/V so that exactly one concurrent
        call.done handler generates the loop.done event and evaluates
        downstream arcs.  All other concurrent callers receive False and
        must not dispatch loop.done.

        Returns:
            True  — this caller is the designated loop.done dispatcher.
            False — another caller already claimed it, or the state was
                    not found / could not be updated.
        """
        if not self._kv:
            await self.connect()

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        max_retries = 10
        for attempt in range(max_retries):
            try:
                entry = await self._kv.get(key)
                if not entry:
                    logger.warning(
                        "try_claim_loop_done: loop state not found for %s (execution=%s)",
                        step_name,
                        execution_id,
                    )
                    return False

                state = json.loads(entry.value.decode("utf-8"))

                if state.get("loop_done_claimed", False):
                    return False  # Another handler already owns this loop.done

                state["loop_done_claimed"] = True
                state["loop_done_claimed_at"] = _utcnow_iso()
                state["updated_at"] = _utcnow_iso()

                value = json.dumps(state).encode("utf-8")
                await self._kv.update(key, value, last=entry.revision)
                logger.info(
                    "try_claim_loop_done: claimed loop.done for %s (execution=%s event_id=%s)",
                    step_name,
                    execution_id,
                    event_id,
                )
                return True

            except KeyNotFoundError:
                logger.debug(
                    "try_claim_loop_done: key not found for %s (execution=%s) — loop state not initialised yet",
                    step_name,
                    execution_id,
                )
                return False
            except Exception as e:
                err = str(e).lower()
                if "wrong last sequence" in err and attempt < max_retries - 1:
                    base = min(0.002 * (2 ** min(attempt, 6)), 0.1)
                    sleep_seconds = base * (0.5 + random.random())
                    await asyncio.sleep(sleep_seconds)
                    continue
                if "wrong last sequence" in err:
                    logger.warning(
                        "try_claim_loop_done: could not claim after %s retries "
                        "(execution=%s step=%s event_id=%s)",
                        max_retries,
                        execution_id,
                        step_name,
                        event_id,
                    )
                else:
                    logger.error("try_claim_loop_done: unexpected error: %s", e)
                return False

        return False

    async def claim_next_loop_index(
        self,
        execution_id: str,
        step_name: str,
        collection_size: int,
        max_in_flight: int,
        event_id: Optional[str] = None,
    ) -> Optional[int]:
        """Atomically claim the next loop iteration index with backpressure control.

        Returns:
            Claimed zero-based index, or None when no slot is currently available.
        """
        if not self._kv:
            await self.connect()

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        safe_collection_size = max(0, int(collection_size or 0))
        safe_max_in_flight = max(1, int(max_in_flight or 1))

        max_retries = 5
        for attempt in range(max_retries):
            try:
                entry = await self._kv.get(key)
                if not entry:
                    return None

                state = json.loads(entry.value.decode("utf-8"))

                completed_count = int(state.get("completed_count", 0) or 0)
                scheduled_count = int(state.get("scheduled_count", completed_count) or completed_count)

                # Ensure state is coherent even if old payloads omitted fields.
                if scheduled_count < completed_count:
                    scheduled_count = completed_count
                state["completed_count"] = completed_count
                state["scheduled_count"] = scheduled_count

                existing_collection_size = int(state.get("collection_size", 0) or 0)
                if safe_collection_size <= 0 and existing_collection_size > 0:
                    safe_collection_size = existing_collection_size

                if safe_collection_size <= 0:
                    state["collection_size"] = 0
                    state["updated_at"] = _utcnow_iso()
                    value = json.dumps(state).encode("utf-8")
                    await self._kv.update(key, value, last=entry.revision)
                    return None

                if scheduled_count >= safe_collection_size:
                    return None

                in_flight = max(0, scheduled_count - completed_count)
                if in_flight >= safe_max_in_flight:
                    return None

                claimed_index = scheduled_count
                state["collection_size"] = safe_collection_size
                state["scheduled_count"] = scheduled_count + 1
                now_iso = _utcnow_iso()
                state["last_claimed_at"] = now_iso
                state["last_progress_at"] = now_iso
                state["updated_at"] = now_iso

                value = json.dumps(state).encode("utf-8")
                await self._kv.update(key, value, last=entry.revision)
                return claimed_index

            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < max_retries - 1:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.error(f"Failed to claim next loop index: {e}")
                return None

        return None

    async def release_loop_slot(
        self,
        execution_id: str,
        step_name: str,
        event_id: Optional[str] = None,
    ) -> bool:
        """Release a previously claimed loop iteration slot by decrementing scheduled_count.

        This is the inverse of claim_next_loop_index and must be called when a slot
        was claimed via NATS but cannot be used (e.g., local collection is smaller than
        the NATS-side collection_size hint).  Prevents in-flight saturation from leaked
        slots that block all further loop dispatch.

        Returns True if the slot was successfully released, False otherwise.
        """
        if not self._kv:
            await self.connect()

        key_suffix = f"loop:{step_name}:{event_id}" if event_id else f"loop:{step_name}"
        key = self._make_key(execution_id, key_suffix)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                entry = await self._kv.get(key)
                if not entry:
                    return False

                state = json.loads(entry.value.decode("utf-8"))

                scheduled_count = int(state.get("scheduled_count", 0) or 0)
                completed_count = int(state.get("completed_count", 0) or 0)
                if scheduled_count <= completed_count:
                    # Nothing to release — would underflow below completed
                    return False

                state["scheduled_count"] = scheduled_count - 1
                state["updated_at"] = _utcnow_iso()

                value = json.dumps(state).encode("utf-8")
                await self._kv.update(key, value, last=entry.revision)
                return True

            except Exception as e:
                if "wrong last sequence" in str(e).lower() and attempt < max_retries - 1:
                    await asyncio.sleep(0.01 * (attempt + 1))
                    continue
                logger.error(f"Failed to release loop slot: {e}")
                return False

        return False

    async def get_loop_completed_count(self, execution_id: str, step_name: str, event_id: Optional[str] = None) -> int:
        """Get the completed iteration count for a loop.

        Args:
            execution_id: Execution identifier
            step_name: Name of the step
            event_id: Event ID that initiated this step instance (for uniqueness)

        Returns:
            The completed_count value, or 0 if not found
        """
        state = await self.get_loop_state(execution_id, step_name, event_id)
        if state:
            return state.get("completed_count", 0)
        return 0
    
    async def delete_execution_state(self, execution_id: str):
        """Delete all state for an execution (cleanup)."""
        if not self._kv:
            await self.connect()

        # Delete all keys for this execution (using dot separator).
        # Sanitize execution_id the same way _make_key does so the prefix matches.
        safe_exec_id = _NATS_KEY_INVALID_RE.sub("_", str(execution_id).replace(":", ".")).strip(".")
        prefix = f"exec.{safe_exec_id}."
        try:
            keys = await self._kv.keys()
            for key in keys:
                if key.startswith(prefix):
                    await self._kv.delete(key)
            logger.debug(f"Deleted execution state from NATS K/V: {execution_id}")
        except Exception as e:
            logger.warning(f"Failed to delete execution state: {e}")


# Global cache instance
_nats_cache: Optional[NATSKVCache] = None
_init_lock = asyncio.Lock()


async def get_nats_cache() -> NATSKVCache:
    """Get or create global NATS K/V cache instance."""
    global _nats_cache
    
    async with _init_lock:
        if _nats_cache is None:
            _nats_cache = NATSKVCache()
            # Get NATS URL from environment
            import os
            nats_url = os.getenv("NATS_URL", "nats://nats.nats.svc.cluster.local:4222")
            await _nats_cache.connect(nats_url)
        
        return _nats_cache


async def close_nats_cache():
    """Close global NATS K/V cache connection."""
    global _nats_cache
    if _nats_cache:
        await _nats_cache.close()
        _nats_cache = None
