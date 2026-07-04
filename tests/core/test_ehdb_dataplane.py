"""Tests for the Phase C bounded EHDB data-plane step.

Two layers of coverage:

* Control-flow tests drive a stateful *fake* ``ehdb-local-reference`` helper
  (a small Python script that reads/writes a JSONL log), so the NoETL
  data-plane layer — disabled no-op, control-plane guard, payload/read bounds,
  outcome classification, and secret-free metrics — is exercised without the
  Rust binary.  These run in bare CI.
* A real-binary roundtrip test runs the actual ``ehdb-local-reference`` binary
  when it is discoverable (built locally / bundled in the kind image), and is
  skipped otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from noetl.core.ehdb_adapter import (
    EHDB_HELPER_BIN_ENV,
    discover_ehdb_helper_executable,
)
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
)
from noetl.core.ehdb_dataplane import (
    EHDB_DATAPLANE_MAX_PAYLOAD_BYTES_ENV,
    EHDB_DATAPLANE_MAX_READ_LIMIT_ENV,
    EhdbDataPlaneOutcome,
    append_ehdb_domain_record,
    read_ehdb_domain_records,
    render_ehdb_dataplane_metrics,
    reset_ehdb_dataplane_metrics,
)


# A faithful-but-minimal stateful stand-in for the Rust helper.  It stores one
# JSON object per line keyed by (tenant, namespace, stream) and reproduces the
# append/read contract the dataplane parses.
_FAKE_HELPER = r'''
import json
import sys

def parse(argv):
    op = argv[0]
    flags = {}
    i = 1
    while i < len(argv):
        key = argv[i][2:]
        flags[key] = argv[i + 1]
        i += 2
    return op, flags

def load(path):
    try:
        with open(path) as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except FileNotFoundError:
        return None

op, flags = parse(sys.argv[1:])
log = flags["log"]
tenant = flags.get("tenant", "noetl")
namespace = flags.get("namespace", "default")
stream = flags["stream"]

if op == "append":
    rows = load(log) or []
    same = [r for r in rows if r["tenant"] == tenant and r["namespace"] == namespace and r["stream"] == stream]
    created = len(same) == 0
    seq = len(same) + 1
    payload = flags["payload"]
    row = {
        "tenant": tenant, "namespace": namespace, "stream": stream,
        "subject": flags["subject"], "transaction_id": flags["transaction-id"],
        "payload": payload, "sequence": seq,
    }
    with open(log, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(json.dumps({
        "action": "append", "log_path": log, "tenant": tenant, "namespace": namespace,
        "stream": stream, "subject": flags["subject"], "sequence": seq,
        "byte_len": len(payload.encode("utf-8")), "created_stream": created,
        "stream_record_count": seq, "transaction_count": len(rows) + 1,
    }))
elif op == "read":
    rows = load(log) or []
    recs = [r for r in rows if r["tenant"] == tenant and r["namespace"] == namespace and r["stream"] == stream]
    exists = len(recs) > 0
    after = int(flags["after"]) if "after" in flags else 0
    limit = int(flags["limit"]) if "limit" in flags else 100
    filtered = [r for r in recs if r["sequence"] > after]
    projected = [{
        "sequence": r["sequence"], "subject": r["subject"],
        "transaction_id": r["transaction_id"], "byte_len": len(r["payload"].encode("utf-8")),
        "payload": r["payload"],
    } for r in filtered[:limit]]
    print(json.dumps({
        "action": "read", "log_path": log, "tenant": tenant, "namespace": namespace,
        "stream": stream, "exists": exists,
        "record_count": len(filtered), "returned": len(projected), "records": projected,
    }))
else:
    print("unexpected op", file=sys.stderr)
    sys.exit(4)
'''


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_ehdb_dataplane_metrics()
    yield
    reset_ehdb_dataplane_metrics()


def _fake_helper(tmp_path: Path) -> Path:
    helper = tmp_path / "ehdb-local-reference-fake.py"
    helper.write_text(f"#!{sys.executable}\n{_FAKE_HELPER.lstrip()}", encoding="utf-8")
    helper.chmod(0o755)
    return helper


def _enabled_env(tmp_path: Path, helper: Path, *, role: str = "worker", mode: str = "local_reference") -> dict:
    return {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: mode,
        EHDB_CLIENT_ROLE_ENV: role,
        EHDB_LOCAL_REFERENCE_LOG_ENV: str(tmp_path / "ehdb.jsonl"),
        EHDB_HELPER_BIN_ENV: str(helper),
        "PATH": "/usr/bin",
    }


# --------------------------------------------------------------------------
# Disabled → strict no-op
# --------------------------------------------------------------------------


def test_append_disabled_is_noop(tmp_path):
    log = tmp_path / "ehdb.jsonl"
    result = append_ehdb_domain_record(
        "orders", "orders.placed", "payload",
        env={EHDB_LOCAL_REFERENCE_LOG_ENV: str(log)},
    )
    assert result.outcome is EhdbDataPlaneOutcome.DISABLED
    assert result.append is None
    assert not log.exists()
    assert render_ehdb_dataplane_metrics() == []


def test_read_disabled_is_noop(tmp_path):
    result = read_ehdb_domain_records("orders", env={})
    assert result.outcome is EhdbDataPlaneOutcome.DISABLED
    assert render_ehdb_dataplane_metrics() == []


# --------------------------------------------------------------------------
# Enabled worker/playbook/system → bounded append/read
# --------------------------------------------------------------------------


def test_append_then_read_roundtrip(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)

    first = append_ehdb_domain_record("itin", "itin.created", '{"a":1}', env=env)
    assert first.outcome is EhdbDataPlaneOutcome.APPENDED
    assert first.append is not None
    assert first.append.sequence == 1
    assert first.append.created_stream is True

    second = append_ehdb_domain_record("itin", "itin.updated", '{"a":2}', env=env)
    assert second.append.sequence == 2
    assert second.append.created_stream is False

    read = read_ehdb_domain_records("itin", env=env)
    assert read.outcome is EhdbDataPlaneOutcome.READ
    assert read.read is not None
    assert read.read.record_count == 2
    assert read.read.records[0]["payload"] == '{"a":1}'
    assert read.read.records[1]["subject"] == "itin.updated"


@pytest.mark.parametrize("role", ["worker", "playbook", "system"])
def test_data_plane_roles_allowed(tmp_path, role):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper, role=role)
    result = append_ehdb_domain_record("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbDataPlaneOutcome.APPENDED
    assert result.role.value == role


def test_read_after_and_limit_forwarded(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    for i in range(1, 6):
        append_ehdb_domain_record("evt", "evt.tick", f"p{i}", env=env)

    limited = read_ehdb_domain_records("evt", limit=2, env=env)
    assert limited.read.returned == 2
    after = read_ehdb_domain_records("evt", after=3, env=env)
    assert after.read.records[0]["sequence"] == 4


# --------------------------------------------------------------------------
# Control-plane guard — gateway/api/server never touch the data plane
# --------------------------------------------------------------------------


def test_control_plane_embedding_refused(tmp_path):
    # Valid control-plane embedding env; a data-plane append must be refused
    # and the helper must never run (no log file created).
    helper = _fake_helper(tmp_path)
    env = {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: "control_plane",
        EHDB_CLIENT_ROLE_ENV: "gateway",
        EHDB_HELPER_BIN_ENV: str(helper),
        "PATH": "/usr/bin",
    }
    result = append_ehdb_domain_record("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbDataPlaneOutcome.GUARD_REFUSED
    assert result.append is None
    assert not (tmp_path / "ehdb.jsonl").exists()


@pytest.mark.parametrize("role", ["server", "api", "gateway"])
def test_control_plane_role_with_data_plane_env_refused(tmp_path, role):
    # A control-plane role handed a data-plane (local_reference) env is a
    # misconfiguration; the contract rejects it and we classify it as a guard
    # refusal (never an append).
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper, role=role)
    result = read_ehdb_domain_records("s", env=env)
    assert result.outcome is EhdbDataPlaneOutcome.GUARD_REFUSED
    assert not (tmp_path / "ehdb.jsonl").exists()


# --------------------------------------------------------------------------
# Bounds — payload size + read limit owned by NoETL
# --------------------------------------------------------------------------


def test_oversize_payload_rejected(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    env[EHDB_DATAPLANE_MAX_PAYLOAD_BYTES_ENV] = "8"
    result = append_ehdb_domain_record("s", "s.evt", "0123456789", env=env)
    assert result.outcome is EhdbDataPlaneOutcome.REJECTED
    assert "exceeds bound" in (result.detail or "")
    assert not (tmp_path / "ehdb.jsonl").exists()


def test_empty_payload_rejected(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    result = append_ehdb_domain_record("s", "s.evt", "", env=env)
    assert result.outcome is EhdbDataPlaneOutcome.REJECTED
    assert not (tmp_path / "ehdb.jsonl").exists()


def test_read_limit_clamped_to_bound(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    env[EHDB_DATAPLANE_MAX_READ_LIMIT_ENV] = "2"
    for i in range(1, 6):
        append_ehdb_domain_record("evt", "evt.tick", f"p{i}", env=env)
    # Request 100 but the bound is 2.
    result = read_ehdb_domain_records("evt", limit=100, env=env)
    assert result.read.returned == 2


# --------------------------------------------------------------------------
# Invalid config + degraded helper
# --------------------------------------------------------------------------


def test_missing_log_is_invalid(tmp_path):
    helper = _fake_helper(tmp_path)
    env = {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: "local_reference",
        EHDB_CLIENT_ROLE_ENV: "worker",
        EHDB_HELPER_BIN_ENV: str(helper),
        "PATH": "/usr/bin",
    }
    result = append_ehdb_domain_record("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbDataPlaneOutcome.INVALID
    assert not (tmp_path / "ehdb.jsonl").exists()


def test_helper_error_is_unavailable(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(2)\n", encoding="utf-8")
    broken.chmod(0o755)
    env = _enabled_env(tmp_path, broken)
    result = append_ehdb_domain_record("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbDataPlaneOutcome.UNAVAILABLE
    assert result.degraded is True


# --------------------------------------------------------------------------
# Observability — metrics carry no secret values
# --------------------------------------------------------------------------


def test_metrics_exclude_payload_and_stream_values(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    secret_payload = "super-secret-token-ABC123"
    append_ehdb_domain_record("private-stream", "s.evt", secret_payload, env=env)
    read_ehdb_domain_records("private-stream", env=env)

    rendered = "\n".join(render_ehdb_dataplane_metrics(labels={"worker_id": "w-1"}))
    assert "noetl_ehdb_dataplane_ops_total" in rendered
    assert 'operation="append"' in rendered
    assert 'outcome="appended"' in rendered
    assert 'operation="read"' in rendered
    # Neither the payload nor the stream name may leak into the metric text.
    assert secret_payload not in rendered
    assert "private-stream" not in rendered


def test_disabled_records_no_metric(tmp_path):
    append_ehdb_domain_record("s", "s.evt", "x", env={})
    assert render_ehdb_dataplane_metrics() == []


# --------------------------------------------------------------------------
# Real binary roundtrip (skipped when the binary is not discoverable)
# --------------------------------------------------------------------------


def test_real_binary_append_read_roundtrip(tmp_path):
    binary = discover_ehdb_helper_executable({"PATH": ""})
    if binary is None:
        pytest.skip("ehdb-local-reference binary not built/discoverable")
    env = {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: "local_reference",
        EHDB_CLIENT_ROLE_ENV: "worker",
        EHDB_LOCAL_REFERENCE_LOG_ENV: str(tmp_path / "real.jsonl"),
        EHDB_HELPER_BIN_ENV: binary,
        "PATH": "/usr/bin",
    }
    appended = append_ehdb_domain_record("muno", "muno.created", '{"city":"paris"}', env=env)
    assert appended.outcome is EhdbDataPlaneOutcome.APPENDED
    assert appended.append.sequence == 1

    read = read_ehdb_domain_records("muno", env=env)
    assert read.outcome is EhdbDataPlaneOutcome.READ
    assert read.read.records[0]["payload"] == '{"city":"paris"}'

    absent = read_ehdb_domain_records("never", env=env)
    assert absent.outcome is EhdbDataPlaneOutcome.ABSENT
