from noetl.claim_policy import decide_reclaim_for_existing_claim


def test_reclaim_when_worker_inactive_even_if_lease_not_expired():
    decision = decide_reclaim_for_existing_claim(
        existing_worker="worker-a",
        requesting_worker="worker-b",
        claim_age_seconds=10.0,
        lease_seconds=120.0,
        worker_runtime_status="error",
        worker_heartbeat_age_seconds=1.0,
        heartbeat_stale_seconds=30.0,
        healthy_worker_hard_timeout_seconds=1800.0,
    )

    assert decision.reclaim is True
    assert decision.reason == "worker_inactive"


def test_keep_claim_for_healthy_worker_after_soft_lease():
    decision = decide_reclaim_for_existing_claim(
        existing_worker="worker-a",
        requesting_worker="worker-b",
        claim_age_seconds=130.0,
        lease_seconds=120.0,
        worker_runtime_status="ready",
        worker_heartbeat_age_seconds=5.0,
        heartbeat_stale_seconds=30.0,
        healthy_worker_hard_timeout_seconds=1800.0,
    )

    assert decision.reclaim is False
    assert decision.retry_reason == "healthy_worker_active"


def test_reclaim_healthy_worker_after_hard_timeout():
    decision = decide_reclaim_for_existing_claim(
        existing_worker="worker-a",
        requesting_worker="worker-b",
        claim_age_seconds=1900.0,
        lease_seconds=120.0,
        worker_runtime_status="ready",
        worker_heartbeat_age_seconds=2.0,
        heartbeat_stale_seconds=30.0,
        healthy_worker_hard_timeout_seconds=1800.0,
    )

    assert decision.reclaim is True
    assert decision.reason == "healthy_worker_hard_timeout"


def test_reclaim_on_lease_expiry_when_worker_health_unknown():
    decision = decide_reclaim_for_existing_claim(
        existing_worker="worker-a",
        requesting_worker="worker-b",
        claim_age_seconds=180.0,
        lease_seconds=120.0,
        worker_runtime_status=None,
        worker_heartbeat_age_seconds=None,
        heartbeat_stale_seconds=30.0,
        healthy_worker_hard_timeout_seconds=1800.0,
    )

    assert decision.reclaim is True
    assert decision.reason == "lease_expired"
