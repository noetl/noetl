from datetime import datetime, timedelta, timezone


def test_result_ref_serializes_optional_ipc_hint():
    from noetl.core.storage import IpcHint, ResultRef, ResultRefMeta, Scope, StoreTier

    hint = IpcHint(
        shm_name="/noetl-execution-frame-1",
        schema_digest="sha256:abc",
        byte_length=4096,
        row_count=10,
        producer="worker-a",
        node_id="node-a",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
    )
    ref = ResultRef.create(
        execution_id="1",
        name="frame_output",
        store=StoreTier.S3,
        scope=Scope.EXECUTION,
        meta=ResultRefMeta(
            content_type="application/vnd.apache.arrow.stream",
            media_type="application/vnd.apache.arrow.stream",
            bytes=4096,
            sha256="abc",
            schema_digest="sha256:abc",
            row_count=10,
        ),
        ipc=hint,
    )

    encoded = ref.model_dump(mode="json")

    assert encoded["ipc"]["kind"] == "arrow_ipc"
    assert encoded["ipc"]["node_id"] == "node-a"
    assert encoded["ipc"]["schema_digest"] == "sha256:abc"
    assert encoded["meta"]["row_count"] == 10
    assert encoded["store"] == "s3"


def test_ipc_hint_expiration_is_best_effort_only():
    from noetl.core.storage import IpcHint

    hint = IpcHint(
        shm_name="/noetl-old",
        schema_digest="sha256:def",
        byte_length=1,
        lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    assert hint.is_expired() is True
