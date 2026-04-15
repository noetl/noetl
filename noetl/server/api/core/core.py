import os
import asyncio
from typing import Optional
from noetl.core.dsl.engine.executor import ControlFlowEngine, PlaybookRepo, StateStore
from noetl.core.messaging import NATSCommandPublisher
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

# Global engine components
_playbook_repo: Optional[PlaybookRepo] = None
_state_store: Optional[StateStore] = None
_engine: Optional[ControlFlowEngine] = None
_nats_publisher: Optional[NATSCommandPublisher] = None

_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS = float(
    os.getenv("NOETL_CLAIM_DB_ACQUIRE_TIMEOUT_SECONDS", "0.25")
)
_CLAIM_LEASE_SECONDS = max(
    1.0,
    float(os.getenv("NOETL_COMMAND_CLAIM_LEASE_SECONDS", "120")),
)
_CLAIM_ACTIVE_RETRY_AFTER_SECONDS = max(
    1,
    int(os.getenv("NOETL_COMMAND_CLAIM_RETRY_AFTER_SECONDS", "2")),
)
_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS = max(
    0.01,
    float(os.getenv("NOETL_BATCH_ACCEPT_ENQUEUE_TIMEOUT_SECONDS", "0.25")),
)
_BATCH_ACCEPT_QUEUE_MAXSIZE = max(
    1,
    int(os.getenv("NOETL_BATCH_ACCEPT_QUEUE_MAXSIZE", "1024")),
)
_BATCH_ACCEPT_WORKERS = max(
    0,
    int(os.getenv("NOETL_BATCH_ACCEPT_WORKERS", "1")),
)
_BATCH_PROCESSING_TIMEOUT_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_BATCH_PROCESSING_TIMEOUT_SECONDS", "0")),
)
_BATCH_PROCESSING_WARN_SECONDS = max(
    0.1,
    float(os.getenv("NOETL_BATCH_PROCESSING_WARN_SECONDS", "15.0")),
)
_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS = max(
    60000,
    int(os.getenv("NOETL_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS", "300000")),
)
_BATCH_STATUS_STREAM_POLL_SECONDS = max(
    0.1,
    float(os.getenv("NOETL_BATCH_STATUS_STREAM_POLL_SECONDS", "0.5")),
)
_BATCH_MAX_EVENTS_PER_REQUEST = max(
    1,
    int(os.getenv("NOETL_BATCH_MAX_EVENTS_PER_REQUEST", "256")),
)
_BATCH_MAX_PAYLOAD_BYTES = max(
    1024,
    int(os.getenv("NOETL_BATCH_MAX_PAYLOAD_BYTES", str(2 * 1024 * 1024))),
)
_COMMAND_CONTEXT_INLINE_MAX_BYTES = max(
    4096,
    int(os.getenv("NOETL_COMMAND_CONTEXT_INLINE_MAX_BYTES", os.getenv("NOETL_INLINE_MAX_BYTES", "10485760"))),
)
_EVENT_RESULT_CONTEXT_MAX_BYTES = max(
    1024,
    int(os.getenv("NOETL_EVENT_RESULT_CONTEXT_MAX_BYTES", "102400")),
)
_EVENT_RESULT_CONTEXT_MAX_ROWS_PER_COMMAND = max(
    1,
    int(os.getenv("NOETL_EVENT_RESULT_CONTEXT_MAX_ROWS_PER_COMMAND", "5000")),
)
_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS = max(
    5.0,
    float(os.getenv("NOETL_COMMAND_PUBLISH_RECOVERY_DELAY_SECONDS", "20")),
)
_COMMAND_PUBLISH_RECOVERY_JITTER_SECONDS = max(
    0.0,
    float(os.getenv("NOETL_COMMAND_PUBLISH_RECOVERY_JITTER_SECONDS", "2")),
)
_COMMAND_PUBLISH_RECOVERY_MAX_CONCURRENCY = max(
    1,
    int(os.getenv("NOETL_COMMAND_PUBLISH_RECOVERY_MAX_CONCURRENCY", "16")),
)
_COMMAND_TERMINAL_EVENT_TYPES = [
    "command.completed",
    "command.failed",
    "command.cancelled",
]
_EXECUTION_TERMINAL_EVENT_TYPES = [
    "playbook.completed",
    "playbook.failed",
    "workflow.completed",
    "workflow.failed",
    "execution.cancelled",
]

_BATCH_FAILURE_ENQUEUE_TIMEOUT = "ack_timeout"
_BATCH_FAILURE_ENQUEUE_ERROR = "enqueue_error"
_BATCH_FAILURE_QUEUE_UNAVAILABLE = "queue_unavailable"
_BATCH_FAILURE_WORKER_UNAVAILABLE = "worker_unavailable"
_BATCH_FAILURE_PROCESSING_TIMEOUT = "processing_timeout"
_BATCH_FAILURE_PROCESSING_ERROR = "processing_error"

_DB_UNAVAILABLE_SHORT_CIRCUIT = (
    os.getenv("NOETL_DB_UNAVAILABLE_SHORT_CIRCUIT", "true").strip().lower()
    in {"1", "true", "yes", "on"}
)
_DB_UNAVAILABLE_BACKOFF_BASE_SECONDS = max(
    0.1,
    float(os.getenv("NOETL_DB_UNAVAILABLE_BACKOFF_BASE_SECONDS", "1.0")),
)
_DB_UNAVAILABLE_BACKOFF_MAX_SECONDS = max(
    _DB_UNAVAILABLE_BACKOFF_BASE_SECONDS,
    float(os.getenv("NOETL_DB_UNAVAILABLE_BACKOFF_MAX_SECONDS", "30.0")),
)
_DB_UNAVAILABLE_ERROR_MARKERS = (
    "server conn crashed",
    "server login has been failing",
    "server_login_retry",
    "the database system is in recovery mode",
    "the database system is not yet accepting connections",
    "could not connect to server",
    "connection refused",
    "connection reset by peer",
    "terminating connection due to administrator command",
    "admin shutdown",
    "connection is closed",
    "pool closed",
)

_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS = max(
    5.0,
    float(os.getenv("NOETL_COMMAND_WORKER_HEARTBEAT_STALE_SECONDS", "30")),
)
_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS = max(
    _CLAIM_LEASE_SECONDS,
    float(os.getenv("NOETL_COMMAND_CLAIM_HEALTHY_WORKER_HARD_TIMEOUT_SECONDS", "1800")),
)
_STATUS_VALUE_MAX_BYTES = max(
    256,
    int(os.getenv("NOETL_STATUS_VALUE_MAX_BYTES", "10485760")),
)
_STATUS_PREVIEW_ITEMS = max(
    1,
    int(os.getenv("NOETL_STATUS_PREVIEW_ITEMS", "5")),
)
_ACTIVE_CLAIMS_CACHE_TTL_SECONDS = max(
    1.0,
    float(
        os.getenv(
            "NOETL_ACTIVE_CLAIMS_CACHE_TTL_SECONDS",
            str(_CLAIM_WORKER_HEARTBEAT_STALE_SECONDS),
        )
    ),
)
_ACTIVE_CLAIMS_CACHE_MAX_ENTRIES = max(
    128,
    int(os.getenv("NOETL_ACTIVE_CLAIMS_CACHE_MAX_ENTRIES", "5000")),
)
_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS = max(
    0.1,
    float(os.getenv("NOETL_ACTIVE_CLAIMS_CACHE_PRUNE_INTERVAL_SECONDS", "1.0")),
)

def get_engine():
    """Get or initialize engine."""
    global _playbook_repo, _state_store, _engine
    
    if _engine is None:
        _playbook_repo = PlaybookRepo()
        _state_store = StateStore(_playbook_repo)
        _engine = ControlFlowEngine(_playbook_repo, _state_store)
    
    return _engine


async def get_nats_publisher():
    """Get or initialize NATS publisher."""
    global _nats_publisher
    
    if _nats_publisher is None:
        from noetl.core.config import settings
        _nats_publisher = NATSCommandPublisher(
            nats_url=settings.nats_url,
            subject=settings.nats_subject
        )
        await _nats_publisher.connect()
        logger.info(f"NATS publisher initialized: {settings.nats_url}")
    
    return _nats_publisher


_STRICT_RESULT_ALLOWED_KEYS = {"status", "reference", "context", "command_id"}
_STRICT_PAYLOAD_FORBIDDEN_KEYS = {"_internal_data"}
_STRICT_CONTEXT_FORBIDDEN_KEYS = {"_internal_data"}



_COMMAND_TERMINAL_EVENT_TYPES = [
    "command.completed",
    "command.failed",
    "command.cancelled",
]

_EVENT_TYPE_TERMINAL_PREDICATE = (
    "event_type IN ("
    + ", ".join(f"'{e}'" for e in _COMMAND_TERMINAL_EVENT_TYPES)
    + ")"
)
_EVENT_TYPE_ACTIVE_CLAIM_PREDICATE = "event_type IN ('command.claimed', 'command.heartbeat')"
_EVENT_TYPE_CLAIMED_PREDICATE = "event_type = 'command.claimed'"
_EVENT_TYPE_SAME_WORKER_LATEST_PREDICATE = (
    "event_type IN ('command.started', 'command.heartbeat', 'command.completed', 'command.failed')"
)
_COMMAND_EVENT_DEDUPE_TYPES = {
    "call.done",
    "call.error",
    "step.exit",
    "command.started",
    "command.completed",
    "command.failed",
}

def _build_command_id_latest_lookup_sql(
    *,
    inner_select_columns: str,
    outer_select_columns: str,
    event_type_predicate: str,
    alias: str,
) -> str:
    """
    Build latest-event lookup SQL with index-friendly command_id predicates.
    """
    return f"""
        SELECT {outer_select_columns}
        FROM noetl.event {alias}
        WHERE execution_id = %s
          AND {event_type_predicate}
          AND meta ? 'command_id'
          AND meta->>'command_id' = %s
        ORDER BY event_id DESC
        LIMIT 1
    """

_CLAIM_TERMINAL_LOOKUP_SQL = _build_command_id_latest_lookup_sql(
    inner_select_columns="event_type, event_id",
    outer_select_columns="event_type",
    event_type_predicate=_EVENT_TYPE_TERMINAL_PREDICATE,
    alias="terminal_match",
)
_CLAIM_EXISTING_LOOKUP_SQL = _build_command_id_latest_lookup_sql(
    inner_select_columns="event_id, worker_id, meta, created_at",
    outer_select_columns="event_id, worker_id, meta, created_at",
    event_type_predicate=_EVENT_TYPE_ACTIVE_CLAIM_PREDICATE,
    alias="claimed_match",
)
_CLAIM_SAME_WORKER_LATEST_LOOKUP_SQL = _build_command_id_latest_lookup_sql(
    inner_select_columns="event_type, event_id",
    outer_select_columns="event_type",
    event_type_predicate=_EVENT_TYPE_SAME_WORKER_LATEST_PREDICATE,
    alias="same_worker_latest_match",
)
_HANDLE_EVENT_CLAIMED_LOOKUP_SQL = _build_command_id_latest_lookup_sql(
    inner_select_columns="worker_id, meta, event_id",
    outer_select_columns="worker_id, meta",
    event_type_predicate=_EVENT_TYPE_CLAIMED_PREDICATE,
    alias="claimed_event",
)

