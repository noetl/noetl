"""Bounded, stateless EHDB worker/playbook readiness hook for NoETL.

Phase B of the EHDB↔NoETL integration.  This module turns the
side-effect-free adapter surface in :mod:`noetl.core.ehdb_adapter` into a
readiness *preflight* that a worker/playbook/system process can run at
bootstrap (or as a standalone command / kind smoke step) to confirm the
EHDB local-reference summary is reachable.

Hard boundaries preserved (see the EHDB Architecture wiki):

* **Disabled by default** — when ``NOETL_EHDB_ENABLED`` is not truthy the
  evaluation is a strict no-op: it performs no read, records no metric, and
  the process behaves byte-identically to a build without this module.
* **Control-plane roles get no data-plane handle** — gateway / api / server
  never perform the local-reference read.  A control-plane role that reaches
  the data-plane read is refused by :func:`assert_data_plane_read_allowed`,
  a defense-in-depth guard beyond the contract validation.
* **Bounded + stateless** — the readiness read shells out to the bounded
  ``ehdb-local-reference summary`` helper under a short time cap and returns a
  fixed-shape count summary.  No long-lived connection or per-tenant state is
  held between requests.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping, Sequence

from noetl.core.ehdb_adapter import (
    LocalReferenceEhdbSummary,
    read_ehdb_local_reference_summary_from_env,
)
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    NOETL_RUN_MODE_ENV,
    EhdbClientRole,
)


# Readiness is a fast preflight, so it uses a much tighter default time cap
# than the adapter's 30s helper default.  Operators may override within a
# clamped range; the clamp keeps the read bounded regardless of the value.
DEFAULT_READINESS_TIMEOUT_SECONDS = 5.0
_MIN_READINESS_TIMEOUT_SECONDS = 0.1
_MAX_READINESS_TIMEOUT_SECONDS = 30.0
EHDB_READINESS_TIMEOUT_ENV = "NOETL_EHDB_READINESS_TIMEOUT_SECONDS"

_CONTROL_PLANE_ROLES = frozenset(
    {EhdbClientRole.GATEWAY, EhdbClientRole.API, EhdbClientRole.SERVER}
)
_DATA_PLANE_ROLES = frozenset(
    {EhdbClientRole.WORKER, EhdbClientRole.PLAYBOOK, EhdbClientRole.SYSTEM}
)


class EhdbControlPlaneGuardError(RuntimeError):
    """Raised when a control-plane role attempts the data-plane read."""


class EhdbReadinessOutcome(StrEnum):
    """Terminal classification of a single readiness evaluation."""

    DISABLED = "disabled"          # EHDB off — no-op, byte-identical
    CONTROL_PLANE = "control_plane"  # control-plane role — no data-plane read
    READY = "ready"                # summary read, at least one non-zero count
    EMPTY = "empty"                # summary read, all counts zero (fresh log)
    TRUNCATED = "truncated"        # bounded time cap tripped — degraded read
    UNAVAILABLE = "unavailable"    # helper missing / errored — degraded
    GUARD_REFUSED = "guard_refused"  # control-plane role given a data-plane env
    INVALID = "invalid"            # misconfigured EHDB env (non-guard)


# Outcomes for which the process may proceed.  Guard / invalid are hard
# misconfigurations that a readiness gate should surface loudly.
_READY_OUTCOMES = frozenset(
    {
        EhdbReadinessOutcome.DISABLED,
        EhdbReadinessOutcome.CONTROL_PLANE,
        EhdbReadinessOutcome.READY,
        EhdbReadinessOutcome.EMPTY,
        EhdbReadinessOutcome.TRUNCATED,
        EhdbReadinessOutcome.UNAVAILABLE,
    }
)
# Outcomes that still let the process run but signal something suboptimal.
_DEGRADED_OUTCOMES = frozenset(
    {EhdbReadinessOutcome.TRUNCATED, EhdbReadinessOutcome.UNAVAILABLE}
)


@dataclass(frozen=True)
class EhdbReadinessResult:
    """Structured, secret-free result of a readiness evaluation."""

    outcome: EhdbReadinessOutcome
    role: EhdbClientRole | None = None
    duration_seconds: float = 0.0
    counts: Mapping[str, int] = field(default_factory=dict)
    log_path: str | None = None
    detail: str | None = None

    @property
    def ready(self) -> bool:
        return self.outcome in _READY_OUTCOMES

    @property
    def degraded(self) -> bool:
        return self.outcome in _DEGRADED_OUTCOMES

    @property
    def performed_read(self) -> bool:
        return self.outcome in {
            EhdbReadinessOutcome.READY,
            EhdbReadinessOutcome.EMPTY,
        }

    def as_dict(self) -> dict[str, object]:
        """Secret-free serialisation for health payloads / smoke output."""

        payload: dict[str, object] = {
            "outcome": self.outcome.value,
            "ready": self.ready,
            "degraded": self.degraded,
            "duration_seconds": round(self.duration_seconds, 6),
        }
        if self.role is not None:
            payload["role"] = self.role.value
        if self.log_path is not None:
            payload["log_path"] = self.log_path
        if self.counts:
            payload["counts"] = dict(self.counts)
        if self.detail is not None:
            payload["detail"] = self.detail
        return payload


def assert_data_plane_read_allowed(role: EhdbClientRole) -> None:
    """Guard: only worker/playbook/system roles may run the data-plane read.

    This is defense-in-depth on top of the contract validation in
    :mod:`noetl.core.ehdb_contract`.  A control-plane role must never obtain a
    local-reference data-plane handle, so any attempt to read one is refused
    here before the helper is executed.
    """

    if role in _CONTROL_PLANE_ROLES:
        raise EhdbControlPlaneGuardError(
            f"EHDB data-plane read refused for control-plane role '{role.value}'; "
            "gateway/api/server remain gatekeepers and never touch EHDB data"
        )
    if role not in _DATA_PLANE_ROLES:
        raise EhdbControlPlaneGuardError(
            f"EHDB data-plane read requires a worker/playbook/system role, got '{role.value}'"
        )


def evaluate_ehdb_readiness(
    env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float | None = None,
    record_metrics: bool = True,
) -> EhdbReadinessResult:
    """Evaluate EHDB local-reference readiness for the current role.

    Returns a structured, secret-free :class:`EhdbReadinessResult`.  When EHDB
    is disabled the result is :attr:`EhdbReadinessOutcome.DISABLED` and no
    metric is recorded — behaviour is byte-identical to EHDB being absent.
    """

    source_env = os.environ if env is None else env
    started = time.monotonic()

    def _finish(
        outcome: EhdbReadinessOutcome,
        *,
        role: EhdbClientRole | None = None,
        counts: Mapping[str, int] | None = None,
        log_path: str | None = None,
        detail: str | None = None,
    ) -> EhdbReadinessResult:
        result = EhdbReadinessResult(
            outcome=outcome,
            role=role,
            duration_seconds=time.monotonic() - started,
            counts=dict(counts or {}),
            log_path=log_path,
            detail=detail,
        )
        if record_metrics:
            _METRICS.record(result)
        return result

    # 1. Disabled fast path — strict no-op (no read, no metric side effect).
    if not _truthy(source_env.get(EHDB_ENABLED_ENV)):
        return _finish(EhdbReadinessOutcome.DISABLED)

    role = _safe_client_role(source_env)

    # 2. Build the contract.  A raised error is a genuine misconfiguration; a
    #    control-plane role carrying a data-plane env classifies as a guard.
    try:
        # Imported lazily so the disabled path never touches the contract.
        from noetl.core.ehdb_contract import ehdb_integration_contract_from_env

        contract = ehdb_integration_contract_from_env(source_env)
    except ValueError as exc:
        if role in _CONTROL_PLANE_ROLES:
            return _finish(
                EhdbReadinessOutcome.GUARD_REFUSED, role=role, detail=str(exc)
            )
        return _finish(EhdbReadinessOutcome.INVALID, role=role, detail=str(exc))

    role = contract.role

    # 3. Control-plane roles never perform a data-plane read.
    if contract.role in _CONTROL_PLANE_ROLES:
        return _finish(EhdbReadinessOutcome.CONTROL_PLANE, role=contract.role)

    # 4. Data-plane role: enforce the guard, then run the bounded read.
    try:
        assert_data_plane_read_allowed(contract.role)
    except EhdbControlPlaneGuardError as exc:
        return _finish(
            EhdbReadinessOutcome.GUARD_REFUSED, role=contract.role, detail=str(exc)
        )

    bounded_timeout = _bounded_timeout(source_env, timeout_seconds)
    try:
        summary = read_ehdb_local_reference_summary_from_env(
            source_env, timeout_seconds=bounded_timeout
        )
    except TimeoutError as exc:
        return _finish(
            EhdbReadinessOutcome.TRUNCATED, role=contract.role, detail=str(exc)
        )
    except (ValueError, RuntimeError, OSError) as exc:
        return _finish(
            EhdbReadinessOutcome.UNAVAILABLE, role=contract.role, detail=str(exc)
        )

    if summary is None:
        # Enabled + local_reference should always yield a summary; treat an
        # unexpected None as disabled rather than inventing readiness.
        return _finish(EhdbReadinessOutcome.DISABLED, role=contract.role)

    return _finish(
        _summary_outcome(summary),
        role=contract.role,
        counts=summary.counts,
        log_path=str(summary.log_path),
    )


def _summary_outcome(summary: LocalReferenceEhdbSummary) -> EhdbReadinessOutcome:
    total = sum(summary.counts.values())
    return EhdbReadinessOutcome.EMPTY if total == 0 else EhdbReadinessOutcome.READY


def _bounded_timeout(
    env: Mapping[str, str], timeout_seconds: float | None
) -> float:
    if timeout_seconds is None:
        raw = env.get(EHDB_READINESS_TIMEOUT_ENV)
        if raw is not None and raw.strip():
            try:
                timeout_seconds = float(raw.strip())
            except ValueError:
                timeout_seconds = DEFAULT_READINESS_TIMEOUT_SECONDS
        else:
            timeout_seconds = DEFAULT_READINESS_TIMEOUT_SECONDS
    return max(
        _MIN_READINESS_TIMEOUT_SECONDS,
        min(_MAX_READINESS_TIMEOUT_SECONDS, timeout_seconds),
    )


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
# text.  Metrics carry only the outcome label + aggregate counters; no log
# path, count values, or error text (which could echo helper stderr) leak in.
# ---------------------------------------------------------------------------


class _ReadinessMetrics:
    """In-process accumulator for EHDB readiness checks.

    Disabled evaluations are intentionally *not* recorded so a disabled EHDB
    build renders byte-identical `/metrics` output.
    """

    def __init__(self) -> None:
        self._checks: dict[str, int] = {}
        self._last_outcome: str | None = None
        self._last_duration_seconds: float = 0.0
        self._last_ready: int = 0
        self._last_degraded: int = 0

    def record(self, result: EhdbReadinessResult) -> None:
        if result.outcome is EhdbReadinessOutcome.DISABLED:
            return
        key = result.outcome.value
        self._checks[key] = self._checks.get(key, 0) + 1
        self._last_outcome = key
        self._last_duration_seconds = result.duration_seconds
        self._last_ready = 1 if result.ready else 0
        self._last_degraded = 1 if result.degraded else 0

    def reset(self) -> None:
        self.__init__()

    def has_data(self) -> bool:
        return bool(self._checks)

    def render(self, *, labels: Mapping[str, str] | None = None) -> list[str]:
        if not self._checks:
            return []
        base_labels = dict(labels or {})
        lines = [
            "# HELP noetl_ehdb_readiness_checks_total EHDB readiness checks by outcome",
            "# TYPE noetl_ehdb_readiness_checks_total counter",
        ]
        for outcome in sorted(self._checks):
            merged = dict(base_labels)
            merged["outcome"] = outcome
            lines.append(
                f"noetl_ehdb_readiness_checks_total{_format_labels(merged)} "
                f"{self._checks[outcome]}"
            )
        lines.extend(
            [
                "# HELP noetl_ehdb_readiness_ready Last EHDB readiness gate result (1=ready)",
                "# TYPE noetl_ehdb_readiness_ready gauge",
                f"noetl_ehdb_readiness_ready{_format_labels(base_labels)} {self._last_ready}",
                "# HELP noetl_ehdb_readiness_degraded Last EHDB readiness degraded flag",
                "# TYPE noetl_ehdb_readiness_degraded gauge",
                f"noetl_ehdb_readiness_degraded{_format_labels(base_labels)} {self._last_degraded}",
                "# HELP noetl_ehdb_readiness_last_duration_seconds Last EHDB readiness duration",
                "# TYPE noetl_ehdb_readiness_last_duration_seconds gauge",
                f"noetl_ehdb_readiness_last_duration_seconds{_format_labels(base_labels)} "
                f"{self._last_duration_seconds:.6f}",
            ]
        )
        return lines


_METRICS = _ReadinessMetrics()


def render_ehdb_readiness_metrics(
    *, labels: Mapping[str, str] | None = None
) -> list[str]:
    """Return Prometheus text lines for readiness checks (empty when none)."""

    return _METRICS.render(labels=labels)


def reset_ehdb_readiness_metrics() -> None:
    """Reset the process-local readiness metrics (test helper)."""

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
    "DEFAULT_READINESS_TIMEOUT_SECONDS",
    "EHDB_READINESS_TIMEOUT_ENV",
    "EhdbControlPlaneGuardError",
    "EhdbReadinessOutcome",
    "EhdbReadinessResult",
    "assert_data_plane_read_allowed",
    "evaluate_ehdb_readiness",
    "render_ehdb_readiness_metrics",
    "reset_ehdb_readiness_metrics",
]
