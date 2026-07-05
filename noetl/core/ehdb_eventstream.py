"""Bounded, stateless EHDB worker/playbook event-stream step for NoETL.

Phase D of the EHDB↔NoETL integration (the event-stream integration path).
Phase C added a bounded domain-record append/read; Phase D adds the
durable-consumer *drain* that lets a NoETL worker/playbook mirror
already-emitted NoETL events into a derived EHDB stream and consume them with
explicit ack-after-materialize semantics:

* ``project`` — append one already-emitted NoETL event into the derived EHDB
  local-reference stream (the Phase C ``append`` primitive is the project leg).
* ``consume`` — pull up to ``limit`` records for a durable consumer after its
  ack cursor, creating the consumer on first pull, *without* moving the cursor.
* ``ack`` — advance the durable consumer's cursor after the batch is
  materialized (ack-after-materialize).

**Event-log-authoritative invariant.**  The NoETL event log
(``noetl.event`` in Postgres / NATS JetStream) is the authoritative,
append-only source of truth.  EHDB is a *derived, auxiliary* consumer of
already-emitted NoETL events — this module never writes to the NoETL event
log.  It only ever runs the bounded ``ehdb-local-reference`` helper against the
separate EHDB JSONL fabric named by ``NOETL_EHDB_LOCAL_REFERENCE_LOG``.  There
is deliberately no import of any NoETL event-writer here; "project" mirrors an
event that was already committed to the authoritative log, it does not emit
one.

Hard boundaries preserved (see the EHDB Architecture wiki):

* **Disabled by default** — when ``NOETL_EHDB_ENABLED`` is not truthy every
  operation is a strict no-op: it performs no project/consume/ack, writes no
  file, records no metric, and behaves byte-identically to a build without
  EHDB.
* **Control-plane roles get no data-plane handle** — gateway / api / server
  never project, consume, or ack.  A control-plane role that reaches the data
  plane is refused by :func:`assert_event_stream_access_allowed`
  (defense-in-depth beyond the contract validation), and no helper is executed.
* **Bounded** — the projected payload is capped
  (``NOETL_EHDB_EVENTSTREAM_MAX_PAYLOAD_BYTES``, default 65536, clamped), the
  consume batch is capped (``NOETL_EHDB_EVENTSTREAM_MAX_CONSUME_LIMIT``,
  default 1000, clamped), the ack sequence must be a positive record sequence,
  and the helper runs under a short time cap.  Over-bound requests are rejected
  before the helper is invoked.
* **Stateless** — each call opens the bounded helper, performs one operation,
  and returns.  No long-lived connection, subscription, or per-tenant state is
  held between requests.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from noetl.core.ehdb_adapter import (
    LocalReferenceAckResult,
    LocalReferenceAppendResult,
    LocalReferenceConsumeResult,
    ehdb_local_reference_ack_invocation_from_env,
    ehdb_local_reference_append_invocation_from_env,
    ehdb_local_reference_consume_invocation_from_env,
    execute_ehdb_helper_json,
)
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    NOETL_RUN_MODE_ENV,
    EhdbClientRole,
)
from noetl.core.ehdb_readiness import EhdbControlPlaneGuardError


DEFAULT_EVENTSTREAM_TIMEOUT_SECONDS = 5.0
_MIN_EVENTSTREAM_TIMEOUT_SECONDS = 0.1
_MAX_EVENTSTREAM_TIMEOUT_SECONDS = 30.0
EHDB_EVENTSTREAM_TIMEOUT_ENV = "NOETL_EHDB_EVENTSTREAM_TIMEOUT_SECONDS"

# Payload + consume-batch bounds.  Owned by NoETL (not the helper) so the
# "bounded" property is enforced at the platform boundary.
DEFAULT_MAX_PAYLOAD_BYTES = 65536
_MAX_PAYLOAD_BYTES_CEILING = 1048576
EHDB_EVENTSTREAM_MAX_PAYLOAD_BYTES_ENV = "NOETL_EHDB_EVENTSTREAM_MAX_PAYLOAD_BYTES"

DEFAULT_MAX_CONSUME_LIMIT = 1000
_CONSUME_LIMIT_CEILING = 10000
EHDB_EVENTSTREAM_MAX_CONSUME_LIMIT_ENV = "NOETL_EHDB_EVENTSTREAM_MAX_CONSUME_LIMIT"

_CONTROL_PLANE_ROLES = frozenset(
    {EhdbClientRole.GATEWAY, EhdbClientRole.API, EhdbClientRole.SERVER}
)
_DATA_PLANE_ROLES = frozenset(
    {EhdbClientRole.WORKER, EhdbClientRole.PLAYBOOK, EhdbClientRole.SYSTEM}
)


class EhdbEventStreamOperation(StrEnum):
    """The bounded event-stream operation performed."""

    PROJECT = "project"
    CONSUME = "consume"
    ACK = "ack"


class EhdbEventStreamOutcome(StrEnum):
    """Terminal classification of a single event-stream operation."""

    DISABLED = "disabled"            # EHDB off — no-op, byte-identical
    PROJECTED = "projected"          # one NoETL event mirrored into EHDB
    CONSUMED = "consumed"            # durable-consumer pull (possibly empty)
    ABSENT = "absent"               # consume of a stream never projected to
    ACKED = "acked"                  # durable-consumer cursor advanced
    REJECTED = "rejected"            # request exceeded a NoETL bound
    TRUNCATED = "truncated"          # bounded time cap tripped — degraded
    UNAVAILABLE = "unavailable"      # helper missing / errored — degraded
    GUARD_REFUSED = "guard_refused"  # control-plane role given a data-plane env
    INVALID = "invalid"              # misconfigured EHDB env (non-guard)


_OK_OUTCOMES = frozenset(
    {
        EhdbEventStreamOutcome.DISABLED,
        EhdbEventStreamOutcome.PROJECTED,
        EhdbEventStreamOutcome.CONSUMED,
        EhdbEventStreamOutcome.ABSENT,
        EhdbEventStreamOutcome.ACKED,
    }
)
_DEGRADED_OUTCOMES = frozenset(
    {EhdbEventStreamOutcome.TRUNCATED, EhdbEventStreamOutcome.UNAVAILABLE}
)


@dataclass(frozen=True)
class EhdbEventStreamResult:
    """Structured result of a bounded event-stream operation."""

    operation: EhdbEventStreamOperation
    outcome: EhdbEventStreamOutcome
    role: EhdbClientRole | None = None
    duration_seconds: float = 0.0
    detail: str | None = None
    project: LocalReferenceAppendResult | None = None
    consume: LocalReferenceConsumeResult | None = None
    ack: LocalReferenceAckResult | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in _OK_OUTCOMES

    @property
    def degraded(self) -> bool:
        return self.outcome in _DEGRADED_OUTCOMES

    @property
    def performed_operation(self) -> bool:
        return self.outcome in {
            EhdbEventStreamOutcome.PROJECTED,
            EhdbEventStreamOutcome.CONSUMED,
            EhdbEventStreamOutcome.ABSENT,
            EhdbEventStreamOutcome.ACKED,
        }

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "operation": self.operation.value,
            "outcome": self.outcome.value,
            "ok": self.ok,
            "degraded": self.degraded,
            "duration_seconds": round(self.duration_seconds, 6),
        }
        if self.role is not None:
            payload["role"] = self.role.value
        if self.detail is not None:
            payload["detail"] = self.detail
        if self.project is not None:
            payload["project"] = self.project.as_dict()
        if self.consume is not None:
            payload["consume"] = self.consume.as_dict()
        if self.ack is not None:
            payload["ack"] = self.ack.as_dict()
        return payload


def assert_event_stream_access_allowed(
    role: EhdbClientRole, *, operation: EhdbEventStreamOperation
) -> None:
    """Guard: only worker/playbook/system roles may drive the event stream.

    Defense-in-depth on top of the contract validation.  A control-plane role
    (gateway/api/server) must never project into, consume from, or ack an EHDB
    stream, so any attempt is refused here before the helper is executed.
    """

    if role in _CONTROL_PLANE_ROLES:
        raise EhdbControlPlaneGuardError(
            f"EHDB event-stream {operation.value} refused for control-plane role "
            f"'{role.value}'; gateway/api/server remain gatekeepers and never "
            "touch EHDB data"
        )
    if role not in _DATA_PLANE_ROLES:
        raise EhdbControlPlaneGuardError(
            f"EHDB event-stream {operation.value} requires a worker/playbook/system "
            f"role, got '{role.value}'"
        )


def project_ehdb_event(
    stream: str,
    subject: str,
    payload: str,
    *,
    transaction_id: str | None = None,
    tenant: str | None = None,
    namespace: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    record_metrics: bool = True,
) -> EhdbEventStreamResult:
    """Mirror one already-emitted NoETL event into the derived EHDB stream.

    This is the project leg of the drain.  The event was already committed to
    the authoritative NoETL event log; this only appends a derived copy into
    the EHDB local-reference stream.  When EHDB is disabled the result is
    :attr:`EhdbEventStreamOutcome.DISABLED` and nothing is written.
    """

    source_env = os.environ if env is None else env
    started = time.monotonic()
    op = EhdbEventStreamOperation.PROJECT

    def _finish(outcome, **kwargs) -> EhdbEventStreamResult:
        return _record(
            EhdbEventStreamResult(
                operation=op,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
                **kwargs,
            ),
            record_metrics,
        )

    if not _truthy(source_env.get(EHDB_ENABLED_ENV)):
        return _finish(EhdbEventStreamOutcome.DISABLED)

    role, guard_result = _resolve_role(source_env, op, started, record_metrics)
    if guard_result is not None:
        return guard_result

    max_bytes = _bounded_max_payload_bytes(source_env)
    payload_bytes = len(payload.encode("utf-8"))
    if payload_bytes == 0:
        return _finish(
            EhdbEventStreamOutcome.REJECTED,
            role=role,
            detail="empty event payload",
        )
    if payload_bytes > max_bytes:
        return _finish(
            EhdbEventStreamOutcome.REJECTED,
            role=role,
            detail=f"payload {payload_bytes} bytes exceeds bound {max_bytes}",
        )

    txn_id = transaction_id or _new_transaction_id()
    bounded_timeout = _bounded_timeout(source_env, timeout_seconds)
    try:
        invocation = ehdb_local_reference_append_invocation_from_env(
            source_env,
            stream=stream,
            subject=subject,
            transaction_id=txn_id,
            payload=payload,
            tenant=tenant,
            namespace=namespace,
        )
    except ValueError as exc:
        return _finish(EhdbEventStreamOutcome.INVALID, role=role, detail=str(exc))
    if invocation is None:
        return _finish(EhdbEventStreamOutcome.DISABLED, role=role)

    try:
        execution = execute_ehdb_helper_json(invocation, timeout_seconds=bounded_timeout)
        result = LocalReferenceAppendResult.from_payload(execution.json_payload)
    except TimeoutError as exc:
        return _finish(EhdbEventStreamOutcome.TRUNCATED, role=role, detail=str(exc))
    except (ValueError, RuntimeError, OSError) as exc:
        return _finish(EhdbEventStreamOutcome.UNAVAILABLE, role=role, detail=str(exc))

    return _finish(EhdbEventStreamOutcome.PROJECTED, role=role, project=result)


def consume_ehdb_events(
    stream: str,
    consumer: str,
    *,
    transaction_id: str | None = None,
    limit: int | None = None,
    tenant: str | None = None,
    namespace: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    record_metrics: bool = True,
) -> EhdbEventStreamResult:
    """Pull up to ``limit`` records for a durable consumer (cursor unchanged)."""

    source_env = os.environ if env is None else env
    started = time.monotonic()
    op = EhdbEventStreamOperation.CONSUME

    def _finish(outcome, **kwargs) -> EhdbEventStreamResult:
        return _record(
            EhdbEventStreamResult(
                operation=op,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
                **kwargs,
            ),
            record_metrics,
        )

    if not _truthy(source_env.get(EHDB_ENABLED_ENV)):
        return _finish(EhdbEventStreamOutcome.DISABLED)

    role, guard_result = _resolve_role(source_env, op, started, record_metrics)
    if guard_result is not None:
        return guard_result

    bounded_limit = _bounded_consume_limit(source_env, limit)
    txn_id = transaction_id or _new_transaction_id()
    bounded_timeout = _bounded_timeout(source_env, timeout_seconds)
    try:
        invocation = ehdb_local_reference_consume_invocation_from_env(
            source_env,
            stream=stream,
            consumer=consumer,
            transaction_id=txn_id,
            limit=bounded_limit,
            tenant=tenant,
            namespace=namespace,
        )
    except ValueError as exc:
        return _finish(EhdbEventStreamOutcome.INVALID, role=role, detail=str(exc))
    if invocation is None:
        return _finish(EhdbEventStreamOutcome.DISABLED, role=role)

    try:
        execution = execute_ehdb_helper_json(invocation, timeout_seconds=bounded_timeout)
        result = LocalReferenceConsumeResult.from_payload(execution.json_payload)
    except TimeoutError as exc:
        return _finish(EhdbEventStreamOutcome.TRUNCATED, role=role, detail=str(exc))
    except (ValueError, RuntimeError, OSError) as exc:
        return _finish(EhdbEventStreamOutcome.UNAVAILABLE, role=role, detail=str(exc))

    outcome = (
        EhdbEventStreamOutcome.CONSUMED
        if result.exists
        else EhdbEventStreamOutcome.ABSENT
    )
    return _finish(outcome, role=role, consume=result)


def ack_ehdb_event(
    stream: str,
    consumer: str,
    sequence: int,
    *,
    transaction_id: str | None = None,
    tenant: str | None = None,
    namespace: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    record_metrics: bool = True,
) -> EhdbEventStreamResult:
    """Advance a durable consumer's ack cursor after materialize."""

    source_env = os.environ if env is None else env
    started = time.monotonic()
    op = EhdbEventStreamOperation.ACK

    def _finish(outcome, **kwargs) -> EhdbEventStreamResult:
        return _record(
            EhdbEventStreamResult(
                operation=op,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
                **kwargs,
            ),
            record_metrics,
        )

    if not _truthy(source_env.get(EHDB_ENABLED_ENV)):
        return _finish(EhdbEventStreamOutcome.DISABLED)

    role, guard_result = _resolve_role(source_env, op, started, record_metrics)
    if guard_result is not None:
        return guard_result

    # A real ack names a published record; sequence 0/negative is rejected
    # before the helper is touched (bounded, no wasted subprocess).
    if int(sequence) < 1:
        return _finish(
            EhdbEventStreamOutcome.REJECTED,
            role=role,
            detail=f"ack sequence must be >= 1, got {sequence}",
        )

    txn_id = transaction_id or _new_transaction_id()
    bounded_timeout = _bounded_timeout(source_env, timeout_seconds)
    try:
        invocation = ehdb_local_reference_ack_invocation_from_env(
            source_env,
            stream=stream,
            consumer=consumer,
            transaction_id=txn_id,
            sequence=int(sequence),
            tenant=tenant,
            namespace=namespace,
        )
    except ValueError as exc:
        return _finish(EhdbEventStreamOutcome.INVALID, role=role, detail=str(exc))
    if invocation is None:
        return _finish(EhdbEventStreamOutcome.DISABLED, role=role)

    try:
        execution = execute_ehdb_helper_json(invocation, timeout_seconds=bounded_timeout)
        result = LocalReferenceAckResult.from_payload(execution.json_payload)
    except TimeoutError as exc:
        return _finish(EhdbEventStreamOutcome.TRUNCATED, role=role, detail=str(exc))
    except (ValueError, RuntimeError, OSError) as exc:
        # A backwards / unknown-sequence ack surfaces as a non-zero helper exit
        # (degraded), not a silent success — the drain contract stays explicit.
        return _finish(EhdbEventStreamOutcome.UNAVAILABLE, role=role, detail=str(exc))

    return _finish(EhdbEventStreamOutcome.ACKED, role=role, ack=result)


def _resolve_role(
    source_env: Mapping[str, str],
    op: EhdbEventStreamOperation,
    started: float,
    record_metrics: bool,
) -> tuple[EhdbClientRole | None, EhdbEventStreamResult | None]:
    """Build the contract + enforce the guard.

    Returns ``(role, guard_result)``.  When ``guard_result`` is not ``None`` the
    caller must return it immediately (guard refusal / invalid config); no
    event-stream operation is performed.
    """

    role = _safe_client_role(source_env)

    def _finish(outcome, **kwargs) -> EhdbEventStreamResult:
        return _record(
            EhdbEventStreamResult(
                operation=op,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
                **kwargs,
            ),
            record_metrics,
        )

    try:
        from noetl.core.ehdb_contract import ehdb_integration_contract_from_env

        contract = ehdb_integration_contract_from_env(source_env)
    except ValueError as exc:
        if role in _CONTROL_PLANE_ROLES:
            return role, _finish(
                EhdbEventStreamOutcome.GUARD_REFUSED, role=role, detail=str(exc)
            )
        return role, _finish(
            EhdbEventStreamOutcome.INVALID, role=role, detail=str(exc)
        )

    try:
        assert_event_stream_access_allowed(contract.role, operation=op)
    except EhdbControlPlaneGuardError as exc:
        return contract.role, _finish(
            EhdbEventStreamOutcome.GUARD_REFUSED, role=contract.role, detail=str(exc)
        )

    return contract.role, None


def _new_transaction_id() -> str:
    """Application-side transaction id (snowflake), per observability rule."""

    try:
        from noetl.core.common import get_snowflake_id_str

        return f"txn-{get_snowflake_id_str()}"
    except Exception:
        return f"txn-{int(time.monotonic() * 1_000_000)}"


def _bounded_timeout(env: Mapping[str, str], timeout_seconds: float | None) -> float:
    if timeout_seconds is None:
        raw = env.get(EHDB_EVENTSTREAM_TIMEOUT_ENV)
        if raw is not None and raw.strip():
            try:
                timeout_seconds = float(raw.strip())
            except ValueError:
                timeout_seconds = DEFAULT_EVENTSTREAM_TIMEOUT_SECONDS
        else:
            timeout_seconds = DEFAULT_EVENTSTREAM_TIMEOUT_SECONDS
    return max(
        _MIN_EVENTSTREAM_TIMEOUT_SECONDS,
        min(_MAX_EVENTSTREAM_TIMEOUT_SECONDS, timeout_seconds),
    )


def _bounded_max_payload_bytes(env: Mapping[str, str]) -> int:
    raw = env.get(EHDB_EVENTSTREAM_MAX_PAYLOAD_BYTES_ENV)
    value = DEFAULT_MAX_PAYLOAD_BYTES
    if raw is not None and raw.strip():
        try:
            value = int(raw.strip())
        except ValueError:
            value = DEFAULT_MAX_PAYLOAD_BYTES
    return max(1, min(_MAX_PAYLOAD_BYTES_CEILING, value))


def _bounded_consume_limit(env: Mapping[str, str], limit: int | None) -> int:
    ceiling = DEFAULT_MAX_CONSUME_LIMIT
    raw = env.get(EHDB_EVENTSTREAM_MAX_CONSUME_LIMIT_ENV)
    if raw is not None and raw.strip():
        try:
            ceiling = int(raw.strip())
        except ValueError:
            ceiling = DEFAULT_MAX_CONSUME_LIMIT
    ceiling = max(1, min(_CONSUME_LIMIT_CEILING, ceiling))
    if limit is None:
        return ceiling
    return max(1, min(ceiling, int(limit)))


def _safe_client_role(env: Mapping[str, str]) -> EhdbClientRole | None:
    raw = env.get(EHDB_CLIENT_ROLE_ENV) or env.get(NOETL_RUN_MODE_ENV) or "worker"
    normalized = raw.strip().lower()
    if normalized == "server":
        return EhdbClientRole.SERVER
    try:
        return EhdbClientRole(normalized)
    except ValueError:
        return None


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


# ---------------------------------------------------------------------------
# Observability — process-local counters rendered into the worker /metrics
# text.  Metrics carry only operation + outcome labels; no stream name,
# subject, consumer, payload, log path, or error text leaks in.
# ---------------------------------------------------------------------------


class _EventStreamMetrics:
    """In-process accumulator for EHDB event-stream operations.

    Disabled operations are intentionally *not* recorded so a disabled EHDB
    build renders byte-identical `/metrics` output.
    """

    def __init__(self) -> None:
        self._ops: dict[tuple[str, str], int] = {}
        self._last_duration_seconds: float = 0.0
        self._last_ok: int = 0
        self._last_degraded: int = 0

    def record(self, result: EhdbEventStreamResult) -> None:
        if result.outcome is EhdbEventStreamOutcome.DISABLED:
            return
        key = (result.operation.value, result.outcome.value)
        self._ops[key] = self._ops.get(key, 0) + 1
        self._last_duration_seconds = result.duration_seconds
        self._last_ok = 1 if result.ok else 0
        self._last_degraded = 1 if result.degraded else 0

    def reset(self) -> None:
        self.__init__()

    def has_data(self) -> bool:
        return bool(self._ops)

    def render(self, *, labels: Mapping[str, str] | None = None) -> list[str]:
        if not self._ops:
            return []
        base_labels = dict(labels or {})
        lines = [
            "# HELP noetl_ehdb_eventstream_ops_total EHDB event-stream operations by operation and outcome",
            "# TYPE noetl_ehdb_eventstream_ops_total counter",
        ]
        for operation, outcome in sorted(self._ops):
            merged = dict(base_labels)
            merged["operation"] = operation
            merged["outcome"] = outcome
            lines.append(
                f"noetl_ehdb_eventstream_ops_total{_format_labels(merged)} "
                f"{self._ops[(operation, outcome)]}"
            )
        lines.extend(
            [
                "# HELP noetl_ehdb_eventstream_last_ok Last EHDB event-stream op result (1=ok)",
                "# TYPE noetl_ehdb_eventstream_last_ok gauge",
                f"noetl_ehdb_eventstream_last_ok{_format_labels(base_labels)} {self._last_ok}",
                "# HELP noetl_ehdb_eventstream_last_degraded Last EHDB event-stream degraded flag",
                "# TYPE noetl_ehdb_eventstream_last_degraded gauge",
                f"noetl_ehdb_eventstream_last_degraded{_format_labels(base_labels)} {self._last_degraded}",
                "# HELP noetl_ehdb_eventstream_last_duration_seconds Last EHDB event-stream op duration",
                "# TYPE noetl_ehdb_eventstream_last_duration_seconds gauge",
                f"noetl_ehdb_eventstream_last_duration_seconds{_format_labels(base_labels)} "
                f"{self._last_duration_seconds:.6f}",
            ]
        )
        return lines


_METRICS = _EventStreamMetrics()


def _record(result: EhdbEventStreamResult, record_metrics: bool) -> EhdbEventStreamResult:
    if record_metrics:
        _METRICS.record(result)
    return result


def render_ehdb_eventstream_metrics(
    *, labels: Mapping[str, str] | None = None
) -> list[str]:
    """Return Prometheus text lines for event-stream ops (empty when none)."""

    return _METRICS.render(labels=labels)


def reset_ehdb_eventstream_metrics() -> None:
    """Reset the process-local event-stream metrics (test helper)."""

    _METRICS.reset()


def _format_labels(labels: Mapping[str, str]) -> str:
    if not labels:
        return ""
    rendered = ",".join(
        f'{key}="{_escape_label(labels[key])}"' for key in sorted(labels)
    )
    return "{" + rendered + "}"


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


__all__ = [
    "DEFAULT_EVENTSTREAM_TIMEOUT_SECONDS",
    "DEFAULT_MAX_CONSUME_LIMIT",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "EHDB_EVENTSTREAM_MAX_CONSUME_LIMIT_ENV",
    "EHDB_EVENTSTREAM_MAX_PAYLOAD_BYTES_ENV",
    "EHDB_EVENTSTREAM_TIMEOUT_ENV",
    "EhdbEventStreamOperation",
    "EhdbEventStreamOutcome",
    "EhdbEventStreamResult",
    "ack_ehdb_event",
    "assert_event_stream_access_allowed",
    "consume_ehdb_events",
    "project_ehdb_event",
    "render_ehdb_eventstream_metrics",
    "reset_ehdb_eventstream_metrics",
]
