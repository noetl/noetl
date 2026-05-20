import json
from pathlib import Path

from noetl.server.api.replay import fold_replay_state
from noetl.server.api.replay.types import ReplaySnapshotSeed
from scripts.check_replay_state_report import main

REGISTRY_DIGEST = "a" * 64


def _replay_state():
    return fold_replay_state(
        [
            {
                "event_id": 1,
                "event_type": "execution.started",
                "status": "RUNNING",
                "execution_id": 123,
            },
            {
                "event_id": 2,
                "event_type": "execution.completed",
                "status": "COMPLETED",
                "execution_id": 123,
            },
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        upcaster_registry_digest=REGISTRY_DIGEST,
    )


def test_check_replay_state_report_accepts_valid_state(tmp_path: Path, capsys):
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(_replay_state()))

    assert main(["--report", str(path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True


def test_check_replay_state_report_rejects_projection_checksum_drift(tmp_path: Path, capsys):
    state = _replay_state()
    state["projection_checksums"]["execution"] = "0" * 64
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["failures"][0]["field"] == "projection_checksums.execution"


def test_check_replay_state_report_rejects_state_checksum_drift(tmp_path: Path, capsys):
    state = _replay_state()
    state["execution"]["status"] = "FAILED"
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "checksum" in fields


def test_check_replay_state_report_rejects_missing_required_fields(tmp_path: Path, capsys):
    state = _replay_state()
    state.pop("tenant_id")
    state.pop("checksum")
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert {"tenant_id", "checksum"} <= fields


def test_check_replay_state_report_requires_sha256_algorithm(tmp_path: Path, capsys):
    state = _replay_state()
    state["checksum_algorithm"] = "md5"
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "checksum_algorithm" in fields


def test_check_replay_state_report_rejects_invalid_registry_digest_shape(
    tmp_path: Path,
    capsys,
):
    state = _replay_state()
    state["upcaster_registry_digest"] = "digest-a"
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "upcaster_registry_digest" in fields


def test_check_replay_state_report_rejects_invalid_field_types(tmp_path: Path, capsys):
    state = _replay_state()
    state["execution_id"] = "not-an-int"
    state["event_count"] = -1
    state["tenant_id"] = ""
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert {"execution_id", "event_count", "tenant_id"} <= fields


def test_check_replay_state_report_rejects_string_integer_fields(tmp_path: Path, capsys):
    state = _replay_state()
    state["execution_id"] = "123"
    state["event_count"] = "4"
    state["last_event_id"] = "9"
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert {"execution_id", "event_count", "last_event_id"} <= fields


def test_check_replay_state_report_rejects_invalid_snapshot_version_without_crashing(
    tmp_path: Path,
    capsys,
):
    state = _replay_state()
    state["replay_snapshot"] = {
        "aggregate_id": "execution/123/all",
        "aggregate_type": "replay_state",
        "version": "not-an-int",
        "checksum": "a" * 64,
        "meta": {"upcaster_registry_digest": REGISTRY_DIGEST},
    }
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "replay_snapshot.version" in fields


def test_check_replay_state_report_rejects_string_snapshot_version(
    tmp_path: Path,
    capsys,
):
    state = _replay_state()
    state["replay_snapshot"] = {
        "aggregate_id": "execution/123/all",
        "aggregate_type": "replay_state",
        "version": "5",
        "checksum": "a" * 64,
        "meta": {"upcaster_registry_digest": REGISTRY_DIGEST},
    }
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "replay_snapshot.version" in fields


def test_check_replay_state_report_rejects_inconsistent_snapshot(tmp_path: Path, capsys):
    base = _replay_state()
    seed = ReplaySnapshotSeed(
        aggregate_id="execution/123/all",
        aggregate_type="replay_state",
        version=2,
        checksum=base["checksum"],
        state=base,
        meta={"upcaster_registry_digest": REGISTRY_DIGEST},
    )
    state = fold_replay_state(
        [
            {
                "event_id": 3,
                "event_type": "execution.completed",
                "status": "COMPLETED",
                "execution_id": 123,
            }
        ],
        tenant_id="tenant-a",
        organization_id="org-a",
        execution_id=123,
        upcaster_registry_digest=REGISTRY_DIGEST,
        base_state=base,
        snapshot_seed=seed,
    )
    state["replay_snapshot"]["meta"]["upcaster_registry_digest"] = "b" * 64
    path = tmp_path / "replay.json"
    path.write_text(json.dumps(state))

    assert main(["--report", str(path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    fields = {failure["field"] for failure in output["failures"]}
    assert "replay_snapshot.meta.upcaster_registry_digest" in fields
