"""Tests for the Phase D bounded EHDB event-stream drain.

Two layers of coverage:

* Control-flow tests drive a stateful *fake* ``ehdb-local-reference`` helper
  (a small Python script that models records + durable-consumer cursors in a
  JSONL log), so the NoETL event-stream layer — disabled no-op, control-plane
  guard, payload/consume bounds, ack-sequence bound, outcome classification,
  secret-free metrics, and the event-log-authoritative invariant — is
  exercised without the Rust binary.  These run in bare CI.
* A real-binary drain test runs the actual ``ehdb-local-reference`` binary when
  it is discoverable (built locally / bundled in the kind image), and is
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
from noetl.core.ehdb_eventstream import (
    EHDB_EVENTSTREAM_MAX_CONSUME_LIMIT_ENV,
    EHDB_EVENTSTREAM_MAX_PAYLOAD_BYTES_ENV,
    EhdbEventStreamOutcome,
    ack_ehdb_event,
    consume_ehdb_events,
    project_ehdb_event,
    render_ehdb_eventstream_metrics,
    reset_ehdb_eventstream_metrics,
)


# A faithful-but-minimal stateful stand-in for the Rust helper.  It stores one
# JSON object per line — records (kind="record") and durable-consumer cursor
# updates (kind="consumer") — and reproduces the append/consume/ack contract
# the event-stream layer parses.
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
        return []

def records_for(rows, tenant, namespace, stream):
    return sorted(
        (r for r in rows if r.get("kind") == "record"
         and r["tenant"] == tenant and r["namespace"] == namespace
         and r["stream"] == stream),
        key=lambda r: r["sequence"],
    )

def cursor_for(rows, tenant, namespace, stream, consumer):
    seen = False
    acked = None
    for r in rows:
        if (r.get("kind") == "consumer" and r["tenant"] == tenant
                and r["namespace"] == namespace and r["stream"] == stream
                and r["consumer"] == consumer):
            seen = True
            acked = r["acked"]
    return seen, acked

op, flags = parse(sys.argv[1:])
log = flags["log"]
tenant = flags.get("tenant", "noetl")
namespace = flags.get("namespace", "default")
stream = flags["stream"]
rows = load(log)

if op == "append":
    same = records_for(rows, tenant, namespace, stream)
    created = len(same) == 0
    seq = len(same) + 1
    payload = flags["payload"]
    row = {
        "kind": "record", "tenant": tenant, "namespace": namespace, "stream": stream,
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
elif op == "consume":
    consumer = flags["consumer"]
    limit = int(flags["limit"]) if "limit" in flags else 100
    recs = records_for(rows, tenant, namespace, stream)
    if not recs:
        print(json.dumps({
            "action": "consume", "log_path": log, "tenant": tenant, "namespace": namespace,
            "stream": stream, "consumer": consumer, "exists": False,
            "created_consumer": False, "acked_sequence": None, "pending_count": 0,
            "returned": 0, "records": [], "transaction_count": len(rows),
        }))
        sys.exit(0)
    seen, acked = cursor_for(rows, tenant, namespace, stream, consumer)
    created = not seen
    if created:
        with open(log, "a") as fh:
            fh.write(json.dumps({
                "kind": "consumer", "tenant": tenant, "namespace": namespace,
                "stream": stream, "consumer": consumer, "acked": None,
            }) + "\n")
    floor = acked or 0
    pending = [r for r in recs if r["sequence"] > floor]
    projected = [{
        "sequence": r["sequence"], "subject": r["subject"],
        "transaction_id": r["transaction_id"],
        "byte_len": len(r["payload"].encode("utf-8")), "payload": r["payload"],
    } for r in pending[:limit]]
    print(json.dumps({
        "action": "consume", "log_path": log, "tenant": tenant, "namespace": namespace,
        "stream": stream, "consumer": consumer, "exists": True,
        "created_consumer": created, "acked_sequence": acked,
        "pending_count": len(pending), "returned": len(projected),
        "records": projected, "transaction_count": len(rows) + (1 if created else 0),
    }))
elif op == "ack":
    consumer = flags["consumer"]
    sequence = int(flags["sequence"])
    recs = records_for(rows, tenant, namespace, stream)
    seqs = {r["sequence"] for r in recs}
    seen, acked = cursor_for(rows, tenant, namespace, stream, consumer)
    if sequence not in seqs:
        print("not found: stream sequence %d" % sequence, file=sys.stderr)
        sys.exit(2)
    if not seen:
        print("not found: consumer %s" % consumer, file=sys.stderr)
        sys.exit(2)
    if acked is not None and sequence < acked:
        print("invalid state: cannot move cursor backwards", file=sys.stderr)
        sys.exit(2)
    with open(log, "a") as fh:
        fh.write(json.dumps({
            "kind": "consumer", "tenant": tenant, "namespace": namespace,
            "stream": stream, "consumer": consumer, "acked": sequence,
        }) + "\n")
    print(json.dumps({
        "action": "ack", "log_path": log, "tenant": tenant, "namespace": namespace,
        "stream": stream, "consumer": consumer, "acked_sequence": sequence,
        "transaction_count": len(rows) + 1,
    }))
else:
    print("unexpected op", file=sys.stderr)
    sys.exit(4)
'''


@pytest.fixture(autouse=True)
def _reset_metrics():
    reset_ehdb_eventstream_metrics()
    yield
    reset_ehdb_eventstream_metrics()


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


def test_project_disabled_is_noop(tmp_path):
    log = tmp_path / "ehdb.jsonl"
    result = project_ehdb_event(
        "events", "noetl.execution.completed", "payload",
        env={EHDB_LOCAL_REFERENCE_LOG_ENV: str(log)},
    )
    assert result.outcome is EhdbEventStreamOutcome.DISABLED
    assert result.project is None
    assert not log.exists()
    assert render_ehdb_eventstream_metrics() == []


def test_consume_and_ack_disabled_are_noop(tmp_path):
    assert consume_ehdb_events("events", "c", env={}).outcome is EhdbEventStreamOutcome.DISABLED
    assert ack_ehdb_event("events", "c", 1, env={}).outcome is EhdbEventStreamOutcome.DISABLED
    assert render_ehdb_eventstream_metrics() == []


# --------------------------------------------------------------------------
# Enabled worker/playbook/system → project → consume → ack → cursor restart
# --------------------------------------------------------------------------


def test_project_consume_ack_drain(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)

    first = project_ehdb_event("events", "noetl.execution.completed", '{"n":1}', env=env)
    assert first.outcome is EhdbEventStreamOutcome.PROJECTED
    assert first.project.sequence == 1
    second = project_ehdb_event("events", "noetl.execution.completed", '{"n":2}', env=env)
    assert second.project.sequence == 2

    consumed = consume_ehdb_events("events", "materializer", env=env)
    assert consumed.outcome is EhdbEventStreamOutcome.CONSUMED
    assert consumed.consume.created_consumer is True
    assert consumed.consume.acked_sequence is None
    assert consumed.consume.pending_count == 2
    assert consumed.consume.returned == 2
    assert consumed.consume.records[0]["sequence"] == 1

    acked = ack_ehdb_event("events", "materializer", 1, env=env)
    assert acked.outcome is EhdbEventStreamOutcome.ACKED
    assert acked.ack.acked_sequence == 1

    # Cursor restart: only the unacked record is pending, consumer not recreated.
    again = consume_ehdb_events("events", "materializer", env=env)
    assert again.consume.created_consumer is False
    assert again.consume.acked_sequence == 1
    assert again.consume.pending_count == 1
    assert again.consume.records[0]["sequence"] == 2


@pytest.mark.parametrize("role", ["worker", "playbook", "system"])
def test_data_plane_roles_allowed(tmp_path, role):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper, role=role)
    result = project_ehdb_event("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbEventStreamOutcome.PROJECTED
    assert result.role.value == role


def test_consume_absent_stream(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    result = consume_ehdb_events("never", "c", env=env)
    assert result.outcome is EhdbEventStreamOutcome.ABSENT
    assert result.consume.exists is False
    assert result.consume.created_consumer is False


# --------------------------------------------------------------------------
# Control-plane guard — gateway/api/server never touch the event stream
# --------------------------------------------------------------------------


def test_control_plane_embedding_refused(tmp_path):
    helper = _fake_helper(tmp_path)
    env = {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: "control_plane",
        EHDB_CLIENT_ROLE_ENV: "gateway",
        EHDB_HELPER_BIN_ENV: str(helper),
        "PATH": "/usr/bin",
    }
    result = project_ehdb_event("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbEventStreamOutcome.GUARD_REFUSED
    assert result.project is None
    assert not (tmp_path / "ehdb.jsonl").exists()


@pytest.mark.parametrize("role", ["server", "api", "gateway"])
def test_control_plane_role_with_data_plane_env_refused(tmp_path, role):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper, role=role)
    result = consume_ehdb_events("s", "c", env=env)
    assert result.outcome is EhdbEventStreamOutcome.GUARD_REFUSED
    assert not (tmp_path / "ehdb.jsonl").exists()


# --------------------------------------------------------------------------
# Bounds — payload size, consume limit, ack sequence owned by NoETL
# --------------------------------------------------------------------------


def test_oversize_payload_rejected(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    env[EHDB_EVENTSTREAM_MAX_PAYLOAD_BYTES_ENV] = "8"
    result = project_ehdb_event("s", "s.evt", "0123456789", env=env)
    assert result.outcome is EhdbEventStreamOutcome.REJECTED
    assert "exceeds bound" in (result.detail or "")
    assert not (tmp_path / "ehdb.jsonl").exists()


def test_empty_payload_rejected(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    result = project_ehdb_event("s", "s.evt", "", env=env)
    assert result.outcome is EhdbEventStreamOutcome.REJECTED
    assert not (tmp_path / "ehdb.jsonl").exists()


def test_consume_limit_clamped_to_bound(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    env[EHDB_EVENTSTREAM_MAX_CONSUME_LIMIT_ENV] = "2"
    for i in range(1, 6):
        project_ehdb_event("evt", "evt.tick", f"p{i}", env=env)
    result = consume_ehdb_events("evt", "c", limit=100, env=env)
    # Bound is 2; all five are pending but only two are returned.
    assert result.consume.pending_count == 5
    assert result.consume.returned == 2


def test_ack_zero_sequence_rejected(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    result = ack_ehdb_event("s", "c", 0, env=env)
    assert result.outcome is EhdbEventStreamOutcome.REJECTED
    assert not (tmp_path / "ehdb.jsonl").exists()


def test_ack_backwards_is_unavailable(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    for i in range(1, 3):
        project_ehdb_event("s", "s.evt", f"p{i}", env=env)
    consume_ehdb_events("s", "c", env=env)
    assert ack_ehdb_event("s", "c", 2, env=env).outcome is EhdbEventStreamOutcome.ACKED
    # Moving the cursor backwards surfaces as a non-zero helper exit (degraded),
    # not a silent success.
    backwards = ack_ehdb_event("s", "c", 1, env=env)
    assert backwards.outcome is EhdbEventStreamOutcome.UNAVAILABLE
    assert backwards.degraded is True


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
    result = project_ehdb_event("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbEventStreamOutcome.INVALID
    assert not (tmp_path / "ehdb.jsonl").exists()


def test_helper_error_is_unavailable(tmp_path):
    broken = tmp_path / "broken.py"
    broken.write_text(f"#!{sys.executable}\nimport sys\nsys.exit(2)\n", encoding="utf-8")
    broken.chmod(0o755)
    env = _enabled_env(tmp_path, broken)
    result = project_ehdb_event("s", "s.evt", "x", env=env)
    assert result.outcome is EhdbEventStreamOutcome.UNAVAILABLE
    assert result.degraded is True


# --------------------------------------------------------------------------
# Event-log-authoritative invariant — EHDB never writes the NoETL event log
# --------------------------------------------------------------------------


def test_project_never_touches_authoritative_event_log(tmp_path):
    # A sentinel standing in for the authoritative NoETL event log.  The drain
    # must only ever write the derived EHDB local-reference log, never this.
    authoritative = tmp_path / "noetl-event-log.sentinel"
    authoritative.write_bytes(b"authoritative-source-of-truth")
    before = authoritative.read_bytes()

    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    project_ehdb_event("events", "noetl.execution.completed", '{"n":1}', env=env)
    consume_ehdb_events("events", "c", env=env)
    ack_ehdb_event("events", "c", 1, env=env)

    # The authoritative log is untouched; only the derived EHDB log grew.
    assert authoritative.read_bytes() == before
    assert (tmp_path / "ehdb.jsonl").exists()


def test_module_does_not_import_noetl_event_writer():
    # Structural guard on the invariant: the event-stream module must not reach
    # for any NoETL event/command writer — it is a derived consumer only.
    source = Path("noetl/core/ehdb_eventstream.py").read_text(encoding="utf-8")
    for forbidden in ("event_log", "noetl.server.event", "outbox", "psycopg", "sqlalchemy"):
        assert forbidden not in source, f"unexpected event-writer reference: {forbidden}"


# --------------------------------------------------------------------------
# Observability — metrics carry no secret values
# --------------------------------------------------------------------------


def test_metrics_exclude_payload_and_stream_values(tmp_path):
    helper = _fake_helper(tmp_path)
    env = _enabled_env(tmp_path, helper)
    secret_payload = "super-secret-token-ABC123"
    project_ehdb_event("private-stream", "s.evt", secret_payload, env=env)
    consume_ehdb_events("private-stream", "secret-consumer", env=env)

    rendered = "\n".join(render_ehdb_eventstream_metrics(labels={"worker_id": "w-1"}))
    assert "noetl_ehdb_eventstream_ops_total" in rendered
    assert 'operation="project"' in rendered
    assert 'outcome="projected"' in rendered
    assert 'operation="consume"' in rendered
    assert secret_payload not in rendered
    assert "private-stream" not in rendered
    assert "secret-consumer" not in rendered


def test_disabled_records_no_metric(tmp_path):
    project_ehdb_event("s", "s.evt", "x", env={})
    assert render_ehdb_eventstream_metrics() == []


# --------------------------------------------------------------------------
# Real binary drain (skipped when the binary is not discoverable)
# --------------------------------------------------------------------------


def test_real_binary_drain_roundtrip(tmp_path):
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
    assert project_ehdb_event("muno", "muno.created", '{"n":1}', env=env).outcome is EhdbEventStreamOutcome.PROJECTED
    assert project_ehdb_event("muno", "muno.created", '{"n":2}', env=env).outcome is EhdbEventStreamOutcome.PROJECTED

    consumed = consume_ehdb_events("muno", "mat", env=env)
    assert consumed.outcome is EhdbEventStreamOutcome.CONSUMED
    assert consumed.consume.pending_count == 2
    assert consumed.consume.created_consumer is True

    assert ack_ehdb_event("muno", "mat", 1, env=env).outcome is EhdbEventStreamOutcome.ACKED

    again = consume_ehdb_events("muno", "mat", env=env)
    assert again.consume.pending_count == 1
    assert again.consume.created_consumer is False
    assert again.consume.acked_sequence == 1
    assert again.consume.records[0]["sequence"] == 2

    absent = consume_ehdb_events("never", "mat", env=env)
    assert absent.outcome is EhdbEventStreamOutcome.ABSENT
