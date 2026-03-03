from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ClaimReclaimDecision:
    reclaim: bool
    reason: Optional[str] = None
    retry_reason: Optional[str] = None


def decide_reclaim_for_existing_claim(
    *,
    existing_worker: Optional[str],
    requesting_worker: str,
    claim_age_seconds: float,
    lease_seconds: float,
    worker_runtime_status: Optional[str],
    worker_heartbeat_age_seconds: Optional[float],
    heartbeat_stale_seconds: float,
    healthy_worker_hard_timeout_seconds: float,
) -> ClaimReclaimDecision:
    """
    Decide whether an existing command claim should be reclaimed.

    Policy goals:
    - Prevent duplicate execution while a healthy worker is still running a long command.
    - Reclaim quickly from inactive/stale workers.
    - Keep an eventual hard timeout to recover from pathological hung commands.
    """
    if not existing_worker or existing_worker == requesting_worker:
        return ClaimReclaimDecision(reclaim=False, retry_reason="same_worker_or_unclaimed")

    status_norm = (worker_runtime_status or "").strip().lower()
    worker_inactive = bool(status_norm) and status_norm != "ready"
    heartbeat_stale = (
        worker_heartbeat_age_seconds is not None
        and worker_heartbeat_age_seconds >= heartbeat_stale_seconds
    )

    if worker_inactive:
        return ClaimReclaimDecision(reclaim=True, reason="worker_inactive")

    if heartbeat_stale:
        return ClaimReclaimDecision(reclaim=True, reason="worker_heartbeat_stale")

    if claim_age_seconds < lease_seconds:
        return ClaimReclaimDecision(reclaim=False, retry_reason="lease_active")

    worker_healthy = (
        status_norm == "ready"
        and worker_heartbeat_age_seconds is not None
        and worker_heartbeat_age_seconds < heartbeat_stale_seconds
    )
    if worker_healthy and claim_age_seconds < healthy_worker_hard_timeout_seconds:
        return ClaimReclaimDecision(reclaim=False, retry_reason="healthy_worker_active")

    if worker_healthy and claim_age_seconds >= healthy_worker_hard_timeout_seconds:
        return ClaimReclaimDecision(reclaim=True, reason="healthy_worker_hard_timeout")

    return ClaimReclaimDecision(reclaim=True, reason="lease_expired")
