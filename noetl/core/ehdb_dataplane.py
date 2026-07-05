"""Bounded, stateless EHDB worker/playbook data-plane step for NoETL.

Phase C of the EHDB↔NoETL integration.  Phase B exposed a *readiness*
preflight (a summary read).  Phase C adds the first bounded *data-plane*
operation: append and read a single domain record through the local-reference
adapter (:mod:`noetl.core.ehdb_adapter`).

Hard boundaries preserved (see the EHDB Architecture wiki):

* **Disabled by default** — when ``NOETL_EHDB_ENABLED`` is not truthy every
  operation is a strict no-op: it performs no append/read, writes no file,
  records no metric, and behaves byte-identically to a build without EHDB.
* **Control-plane roles get no data-plane handle** — gateway / api / server
  never append or read.  A control-plane role that reaches the data-plane is
  refused by :func:`assert_data_plane_access_allowed` (defense-in-depth beyond
  the contract validation), and no helper is executed.
* **Bounded** — the payload is capped (``NOETL_EHDB_DATAPLANE_MAX_PAYLOAD_BYTES``,
  default 65536, clamped) and the read limit is capped
  (``NOETL_EHDB_DATAPLANE_MAX_READ_LIMIT``, default 1000, clamped).  The helper
  runs under a short time cap.  Over-bound requests are rejected before the
  helper is invoked.
* **Stateless** — each call opens the bounded helper, performs one operation,
  and returns.  No long-lived connection or per-tenant state is held between
  requests.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from noetl.core.ehdb_adapter import (
    LocalReferenceAppendResult,
    LocalReferenceReadResult,
    ehdb_local_reference_append_invocation_from_env,
    ehdb_local_reference_read_invocation_from_env,
    execute_ehdb_helper_json,
)
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    NOETL_RUN_MODE_ENV,
    EhdbClientRole,
)
from noetl.core.ehdb_readiness import EhdbControlPlaneGuardError


# A data-plane operation is a fast bounded helper call; use the same tight
# default cap as the readiness preflight.  Operators may override within a
# clamped range that keeps the operation bounded regardless of the value.
DEFAULT_DATAPLANE_TIMEOUT_SECONDS = 5.0
_MIN_DATAPLANE_TIMEOUT_SECONDS = 0.1
_MAX_DATAPLANE_TIMEOUT_SECONDS = 30.0
EHDB_DATAPLANE_TIMEOUT_ENV = "NOETL_EHDB_DATAPLANE_TIMEOUT_SECONDS"

# Payload + read-limit bounds.  The bound is owned by NoETL (not the helper) so
# the "bounded" property is enforced at the platform boundary.
DEFAULT_MAX_PAYLOAD_BYTES = 65536
_MAX_PAYLOAD_BYTES_CEILING = 1048576
EHDB_DATAPLANE_MAX_PAYLOAD_BYTES_ENV = "NOETL_EHDB_DATAPLANE_MAX_PAYLOAD_BYTES"

DEFAULT_MAX_READ_LIMIT = 1000
_READ_LIMIT_CEILING = 10000
EHDB_DATAPLANE_MAX_READ_LIMIT_ENV = "NOETL_EHDB_DATAPLANE_MAX_READ_LIMIT"

_CONTROL_PLANE_ROLES = frozenset(
    {EhdbClientRole.GATEWAY, EhdbClientRole.API, EhdbClientRole.SERVER}
)
_DATA_PLANE_ROLES = frozenset(
    {EhdbClientRole.WORKER, EhdbClientRole.PLAYBOOK, EhdbClientRole.SYSTEM}
)


class EhdbDataPlaneOperation(StrEnum):
    """The bounded data-plane operation performed."""

    APPEND = "append"
    READ = "read"


class EhdbDataPlaneOutcome(StrEnum):
    """Terminal classification of a single data-plane operation."""

    DISABLED = "disabled"            # EHDB off — no-op, byte-identical
    APPENDED = "appended"            # one domain record appended
    READ = "read"                    # domain records read (possibly empty)
    ABSENT = "absent"                # read of a stream that was never written
    REJECTED = "rejected"            # request exceeded a NoETL bound
    TRUNCATED = "truncated"          # bounded time cap tripped — degraded
    UNAVAILABLE = "unavailable"      # helper missing / errored — degraded
    GUARD_REFUSED = "guard_refused"  # control-plane role given a data-plane env
    INVALID = "invalid"              # misconfigured EHDB env (non-guard)


_OK_OUTCOMES = frozenset(
    {
        EhdbDataPlaneOutcome.DISABLED,
        EhdbDataPlaneOutcome.APPENDED,
        EhdbDataPlaneOutcome.READ,
        EhdbDataPlaneOutcome.ABSENT,
    }
)
_DEGRADED_OUTCOMES = frozenset(
    {EhdbDataPlaneOutcome.TRUNCATED, EhdbDataPlaneOutcome.UNAVAILABLE}
)


@dataclass(frozen=True)
class EhdbDataPlaneResult:
    """Structured result of a bounded data-plane operation."""

    operation: EhdbDataPlaneOperation
    outcome: EhdbDataPlaneOutcome
    role: EhdbClientRole | None = None
    duration_seconds: float = 0.0
    detail: str | None = None
    append: LocalReferenceAppendResult | None = None
    read: LocalReferenceReadResult | None = None

    @property
    def ok(self) -> bool:
        return self.outcome in _OK_OUTCOMES

    @property
    def degraded(self) -> bool:
        return self.outcome in _DEGRADED_OUTCOMES

    @property
    def performed_operation(self) -> bool:
        return self.outcome in {
            EhdbDataPlaneOutcome.APPENDED,
            EhdbDataPlaneOutcome.READ,
            EhdbDataPlaneOutcome.ABSENT,
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
        if self.append is not None:
            payload["append"] = self.append.as_dict()
        if self.read is not None:
            payload["read"] = self.read.as_dict()
        return payload


def assert_data_plane_access_allowed(
    role: EhdbClientRole, *, operation: EhdbDataPlaneOperation
) -> None:
    """Guard: only worker/playbook/system roles may touch the data plane.

    Defense-in-depth on top of the contract validation.  A control-plane role
    (gateway/api/server) must never append to or read from EHDB data, so any
    attempt is refused here before the helper is executed.
    """

    if role in _CONTROL_PLANE_ROLES:
        raise EhdbControlPlaneGuardError(
            f"EHDB data-plane {operation.value} refused for control-plane role "
            f"'{role.value}'; gateway/api/server remain gatekeepers and never "
            "touch EHDB data"
        )
    if role not in _DATA_PLANE_ROLES:
        raise EhdbControlPlaneGuardError(
            f"EHDB data-plane {operation.value} requires a worker/playbook/system "
            f"role, got '{role.value}'"
        )


def append_ehdb_domain_record(
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
) -> EhdbDataPlaneResult:
    """Append one bounded domain record via the local-reference adapter.

    When EHDB is disabled the result is
    :attr:`EhdbDataPlaneOutcome.DISABLED` and nothing is written — behaviour is
    byte-identical to EHDB being absent.
    """

    source_env = os.environ if env is None else env
    started = time.monotonic()
    op = EhdbDataPlaneOperation.APPEND

    def _finish(outcome, **kwargs) -> EhdbDataPlaneResult:
        return _record(
            EhdbDataPlaneResult(
                operation=op,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
                **kwargs,
            ),
            record_metrics,
        )

    if not _truthy(source_env.get(EHDB_ENABLED_ENV)):
        return _finish(EhdbDataPlaneOutcome.DISABLED)

    role, contract, guard_result = _resolve_role(source_env, op, started, record_metrics)
    if guard_result is not None:
        return guard_result

    # Bound the payload before touching the helper.
    max_bytes = _bounded_max_payload_bytes(source_env)
    payload_bytes = len(payload.encode("utf-8"))
    if payload_bytes == 0:
        return _finish(
            EhdbDataPlaneOutcome.REJECTED,
            role=role,
            detail="empty domain-record payload",
        )
    if payload_bytes > max_bytes:
        return _finish(
            EhdbDataPlaneOutcome.REJECTED,
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
        return _finish(EhdbDataPlaneOutcome.INVALID, role=role, detail=str(exc))
    if invocation is None:
        return _finish(EhdbDataPlaneOutcome.DISABLED, role=role)

    try:
        execution = execute_ehdb_helper_json(
            invocation, timeout_seconds=bounded_timeout
        )
        result = LocalReferenceAppendResult.from_payload(execution.json_payload)
    except TimeoutError as exc:
        return _finish(EhdbDataPlaneOutcome.TRUNCATED, role=role, detail=str(exc))
    except (ValueError, RuntimeError, OSError) as exc:
        return _finish(EhdbDataPlaneOutcome.UNAVAILABLE, role=role, detail=str(exc))

    return _finish(EhdbDataPlaneOutcome.APPENDED, role=role, append=result)


def read_ehdb_domain_records(
    stream: str,
    *,
    after: int | None = None,
    limit: int | None = None,
    tenant: str | None = None,
    namespace: str | None = None,
    env: Mapping[str, str] | None = None,
    timeout_seconds: float | None = None,
    record_metrics: bool = True,
) -> EhdbDataPlaneResult:
    """Read up to ``limit`` bounded domain records via the adapter."""

    source_env = os.environ if env is None else env
    started = time.monotonic()
    op = EhdbDataPlaneOperation.READ

    def _finish(outcome, **kwargs) -> EhdbDataPlaneResult:
        return _record(
            EhdbDataPlaneResult(
                operation=op,
                outcome=outcome,
                duration_seconds=time.monotonic() - started,
                **kwargs,
            ),
            record_metrics,
        )

    if not _truthy(source_env.get(EHDB_ENABLED_ENV)):
        return _finish(EhdbDataPlaneOutcome.DISABLED)

    role, contract, guard_result = _resolve_role(source_env, op, started, record_metrics)
    if guard_result is not None:
        return guard_result

    bounded_limit = _bounded_read_limit(source_env, limit)
    bounded_timeout = _bounded_timeout(source_env, timeout_seconds)
    try:
        invocation = ehdb_local_reference_read_invocation_from_env(
            source_env,
            stream=stream,
            after=after,
            limit=bounded_limit,
            tenant=tenant,
            namespace=namespace,
        )
    except ValueError as exc:
        return _finish(EhdbDataPlaneOutcome.INVALID, role=role, detail=str(exc))
    if invocation is None:
        return _finish(EhdbDataPlaneOutcome.DISABLED, role=role)

    try:
        execution = execute_ehdb_helper_json(
            invocation, timeout_seconds=bounded_timeout
        )
        result = LocalReferenceReadResult.from_payload(execution.json_payload)
    except TimeoutError as exc:
        return _finish(EhdbDataPlaneOutcome.TRUNCATED, role=role, detail=str(exc))
    except (ValueError, RuntimeError, OSError) as exc:
        return _finish(EhdbDataPlaneOutcome.UNAVAILABLE, role=role, detail=str(exc))

    outcome = (
        EhdbDataPlaneOutcome.READ if result.exists else EhdbDataPlaneOutcome.ABSENT
    )
    return _finish(outcome, role=role, read=result)


def _resolve_role(
    source_env: Mapping[str, str],
    op: EhdbDataPlaneOperation,
    started: float,
    record_metrics: bool,
) -> tuple[EhdbClientRole | None, object | None, EhdbDataPlaneResult | None]:
    """Build the contract + enforce the guard.

    Returns ``(role, contract, guard_result)``.  When ``guard_result`` is not
    ``None`` the caller must return it immediately (guard refusal / invalid
    config); no data-plane operation is performed.
    """

    role = _safe_client_role(source_env)

    def _finish(outcome, **kwargs) -> EhdbDataPlaneResult:
        return _record(
            EhdbDataPlaneResult(
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
            return role, None, _finish(
                EhdbDataPlaneOutcome.GUARD_REFUSED, role=role, detail=str(exc)
            )
        return role, None, _finish(
            EhdbDataPlaneOutcome.INVALID, role=role, detail=str(exc)
        )

    try:
        assert_data_plane_access_allowed(contract.role, operation=op)
    except EhdbControlPlaneGuardError as exc:
        return contract.role, contract, _finish(
            EhdbDataPlaneOutcome.GUARD_REFUSED, role=contract.role, detail=str(exc)
        )

    return contract.role, contract, None


def _new_transaction_id() -> str:
    """Application-side transaction id (snowflake), per observability rule."""

    try:
        from noetl.core.common import get_snowflake_id_str

        return f"txn-{get_snowflake_id_str()}"
    except Exception:
        # Fallback keeps the operation usable in minimal environments; still a
        # valid EHDB identifier ([A-Za-z0-9_-]).
        return f"txn-{int(time.monotonic() * 1_000_000)}"


def _bounded_timeout(env: Mapping[str, str], timeout_seconds: float | None) -> float:
    if timeout_seconds is None:
        raw = env.get(EHDB_DATAPLANE_TIMEOUT_ENV)
        if raw is not None and raw.strip():
            try:
                timeout_seconds = float(raw.strip())
            except ValueError:
                timeout_seconds = DEFAULT_DATAPLANE_TIMEOUT_SECONDS
        else:
            timeout_seconds = DEFAULT_DATAPLANE_TIMEOUT_SECONDS
    return max(
        _MIN_DATAPLANE_TIMEOUT_SECONDS,
        min(_MAX_DATAPLANE_TIMEOUT_SECONDS, timeout_seconds),
    )


def _bounded_max_payload_bytes(env: Mapping[str, str]) -> int:
    raw = env.get(EHDB_DATAPLANE_MAX_PAYLOAD_BYTES_ENV)
    value = DEFAULT_MAX_PAYLOAD_BYTES
    if raw is not None and raw.strip():
        try:
            value = int(raw.strip())
        except ValueError:
            value = DEFAULT_MAX_PAYLOAD_BYTES
    return max(1, min(_MAX_PAYLOAD_BYTES_CEILING, value))


def _bounded_read_limit(env: Mapping[str, str], limit: int | None) -> int:
    ceiling = DEFAULT_MAX_READ_LIMIT
    raw = env.get(EHDB_DATAPLANE_MAX_READ_LIMIT_ENV)
    if raw is not None and raw.strip():
        try:
            ceiling = int(raw.strip())
        except ValueError:
            ceiling = DEFAULT_MAX_READ_LIMIT
    ceiling = max(1, min(_READ_LIMIT_CEILING, ceiling))
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
# subject, payload, log path, or error text leaks in.
# ---------------------------------------------------------------------------


class _DataPlaneMetrics:
    """In-process accumulator for EHDB data-plane operations.

    Disabled operations are intentionally *not* recorded so a disabled EHDB
    build renders byte-identical `/metrics` output.
    """

    def __init__(self) -> None:
        self._ops: dict[tuple[str, str], int] = {}
        self._last_duration_seconds: float = 0.0
        self._last_ok: int = 0
        self._last_degraded: int = 0

    def record(self, result: EhdbDataPlaneResult) -> None:
        if result.outcome is EhdbDataPlaneOutcome.DISABLED:
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
            "# HELP noetl_ehdb_dataplane_ops_total EHDB data-plane operations by operation and outcome",
            "# TYPE noetl_ehdb_dataplane_ops_total counter",
        ]
        for operation, outcome in sorted(self._ops):
            merged = dict(base_labels)
            merged["operation"] = operation
            merged["outcome"] = outcome
            lines.append(
                f"noetl_ehdb_dataplane_ops_total{_format_labels(merged)} "
                f"{self._ops[(operation, outcome)]}"
            )
        lines.extend(
            [
                "# HELP noetl_ehdb_dataplane_last_ok Last EHDB data-plane op result (1=ok)",
                "# TYPE noetl_ehdb_dataplane_last_ok gauge",
                f"noetl_ehdb_dataplane_last_ok{_format_labels(base_labels)} {self._last_ok}",
                "# HELP noetl_ehdb_dataplane_last_degraded Last EHDB data-plane degraded flag",
                "# TYPE noetl_ehdb_dataplane_last_degraded gauge",
                f"noetl_ehdb_dataplane_last_degraded{_format_labels(base_labels)} {self._last_degraded}",
                "# HELP noetl_ehdb_dataplane_last_duration_seconds Last EHDB data-plane op duration",
                "# TYPE noetl_ehdb_dataplane_last_duration_seconds gauge",
                f"noetl_ehdb_dataplane_last_duration_seconds{_format_labels(base_labels)} "
                f"{self._last_duration_seconds:.6f}",
            ]
        )
        return lines


_METRICS = _DataPlaneMetrics()


def _record(result: EhdbDataPlaneResult, record_metrics: bool) -> EhdbDataPlaneResult:
    if record_metrics:
        _METRICS.record(result)
    return result


def render_ehdb_dataplane_metrics(
    *, labels: Mapping[str, str] | None = None
) -> list[str]:
    """Return Prometheus text lines for data-plane ops (empty when none)."""

    return _METRICS.render(labels=labels)


def reset_ehdb_dataplane_metrics() -> None:
    """Reset the process-local data-plane metrics (test helper)."""

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
    "DEFAULT_DATAPLANE_TIMEOUT_SECONDS",
    "DEFAULT_MAX_PAYLOAD_BYTES",
    "DEFAULT_MAX_READ_LIMIT",
    "EHDB_DATAPLANE_MAX_PAYLOAD_BYTES_ENV",
    "EHDB_DATAPLANE_MAX_READ_LIMIT_ENV",
    "EHDB_DATAPLANE_TIMEOUT_ENV",
    "EhdbDataPlaneOperation",
    "EhdbDataPlaneOutcome",
    "EhdbDataPlaneResult",
    "append_ehdb_domain_record",
    "assert_data_plane_access_allowed",
    "read_ehdb_domain_records",
    "render_ehdb_dataplane_metrics",
    "reset_ehdb_dataplane_metrics",
]
