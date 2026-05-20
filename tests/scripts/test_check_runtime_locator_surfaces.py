import json
from pathlib import Path

from scripts.check_runtime_locator_surfaces import main


def test_check_runtime_locator_surfaces_accepts_replay_and_live_rows(tmp_path: Path, capsys):
    command = {
        "command_id": "cmd-1",
        "worker_locator": "noetl://tenant/tenant-a/org/org-a/cluster/cluster-a/node/node-a/worker/worker-cpu-01",
        "locality": {
            "cluster_id": "cluster-a",
            "node_id": "node-a",
            "worker_pool": "worker-cpu-01",
        },
    }
    replay = {
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "commands": {"cmd-1": command},
    }
    live_rows = {
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "rows": {"commands": [command]},
    }
    replay_path = tmp_path / "replay.json"
    live_rows_path = tmp_path / "live-rows.json"
    replay_path.write_text(json.dumps(replay))
    live_rows_path.write_text(json.dumps(live_rows))

    assert main(["--replay-report", str(replay_path), "--live-rows", str(live_rows_path)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is True
    assert output["locator_count"] == 2
    assert output["surfaces"] == {"live_rows.commands": 1, "replay.commands": 1}


def test_check_runtime_locator_surfaces_rejects_malformed_locator(tmp_path: Path, capsys):
    replay = {
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "commands": {
            "cmd-1": {
                "command_id": "cmd-1",
                "worker_locator": "noetl://execution/123/result/load/abcd",
            }
        },
    }
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps(replay))

    assert main(["--replay-report", str(replay_path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["matched"] is False
    assert output["failures"][0]["field"] == "worker_locator"


def test_check_runtime_locator_surfaces_rejects_tenant_mismatch(tmp_path: Path, capsys):
    live_rows = {
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "rows": {
            "commands": [
                {
                    "command_id": "cmd-1",
                    "worker_locator": "noetl://tenant/tenant-b/org/org-a/node/node-a/worker/worker-cpu-01",
                }
            ]
        },
    }
    live_rows_path = tmp_path / "live-rows.json"
    live_rows_path.write_text(json.dumps(live_rows))

    assert main(["--live-rows", str(live_rows_path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "worker_locator.tenant" in {failure["field"] for failure in output["failures"]}


def test_check_runtime_locator_surfaces_rejects_locality_mismatch(tmp_path: Path, capsys):
    replay = {
        "tenant_id": "tenant-a",
        "organization_id": "org-a",
        "commands": {
            "cmd-1": {
                "command_id": "cmd-1",
                "worker_locator": "noetl://tenant/tenant-a/org/org-a/node/node-a/worker/worker-cpu-01",
                "locality": {"node_id": "node-b"},
            }
        },
    }
    replay_path = tmp_path / "replay.json"
    replay_path.write_text(json.dumps(replay))

    assert main(["--replay-report", str(replay_path)]) == 1
    output = json.loads(capsys.readouterr().out)
    assert "locality.node_id" in {failure["field"] for failure in output["failures"]}
