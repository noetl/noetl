import sys
from pathlib import Path

import pytest

from noetl.core.ehdb_adapter import (
    EHDB_HELPER_BIN_ENV,
    EHDB_LOCAL_REFERENCE_SUMMARY_FIELDS,
    EHDB_LOCAL_REFERENCE_HELPER_NAME,
    LocalReferenceEhdbExecution,
    LocalReferenceEhdbAdapter,
    LocalReferenceEhdbInvocation,
    LocalReferenceEhdbSummary,
    discover_ehdb_helper_executable,
    ehdb_adapter_from_env,
    ehdb_helper_invocation_from_env,
    ehdb_local_reference_summary_invocation_from_env,
    execute_ehdb_helper_json,
    execute_ehdb_local_reference_summary_from_env,
    read_ehdb_local_reference_summary_from_env,
)
from noetl.core.ehdb_contract import (
    EHDB_CAPABILITIES_ENV,
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
    EhdbCapability,
    EhdbClientRole,
    EhdbIntegrationMode,
    ehdb_integration_contract_from_env,
)


def test_ehdb_adapter_returns_none_when_disabled():
    assert ehdb_adapter_from_env({}) is None


def test_ehdb_adapter_returns_none_for_control_plane_embedding():
    env = {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: "control_plane",
        EHDB_CLIENT_ROLE_ENV: "gateway",
    }

    assert ehdb_adapter_from_env(env) is None
    assert ehdb_helper_invocation_from_env(env) is None


def test_ehdb_adapter_builds_worker_local_reference_adapter():
    adapter = ehdb_adapter_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
        }
    )

    assert isinstance(adapter, LocalReferenceEhdbAdapter)
    assert adapter.role is EhdbClientRole.WORKER
    assert adapter.local_reference_log == Path("/tmp/noetl-ehdb.jsonl")


def test_ehdb_adapter_builds_playbook_local_reference_adapter():
    adapter = ehdb_adapter_from_env(
        {
            EHDB_ENABLED_ENV: "1",
            EHDB_MODE_ENV: "local_reference",
            EHDB_CLIENT_ROLE_ENV: "playbook",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "var/noetl/ehdb/reference.jsonl",
        }
    )

    assert adapter is not None
    assert adapter.role is EhdbClientRole.PLAYBOOK
    assert adapter.local_reference_log == Path("var/noetl/ehdb/reference.jsonl")


def test_ehdb_adapter_exports_worker_runtime_env():
    adapter = ehdb_adapter_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
        }
    )

    assert adapter is not None
    runtime_env = adapter.runtime_env()

    assert runtime_env == {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: EhdbIntegrationMode.LOCAL_REFERENCE.value,
        EHDB_CLIENT_ROLE_ENV: EhdbClientRole.WORKER.value,
        EHDB_CAPABILITIES_ENV: runtime_env[EHDB_CAPABILITIES_ENV],
        EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
    }
    assert set(runtime_env[EHDB_CAPABILITIES_ENV].split(",")) == {
        capability.value
        for capability in EhdbCapability
        if capability is not EhdbCapability.CONTROL_PLANE
    }


def test_ehdb_helper_invocation_returns_none_when_disabled():
    assert ehdb_helper_invocation_from_env({}) is None


def test_ehdb_helper_invocation_builds_worker_argv_and_env():
    invocation = ehdb_helper_invocation_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            EHDB_HELPER_BIN_ENV: "/opt/noetl/bin/ehdb-local-reference",
        },
        args=("replay", "--dry-run"),
    )

    assert isinstance(invocation, LocalReferenceEhdbInvocation)
    assert invocation.argv == (
        "/opt/noetl/bin/ehdb-local-reference",
        "replay",
        "--dry-run",
    )
    assert invocation.role is EhdbClientRole.WORKER
    assert invocation.local_reference_log == Path("/tmp/noetl-ehdb.jsonl")
    assert invocation.env == {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: EhdbIntegrationMode.LOCAL_REFERENCE.value,
        EHDB_CLIENT_ROLE_ENV: EhdbClientRole.WORKER.value,
        EHDB_CAPABILITIES_ENV: invocation.env[EHDB_CAPABILITIES_ENV],
        EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
    }
    assert EhdbCapability.TRANSACTION_APPEND.value in invocation.env[
        EHDB_CAPABILITIES_ENV
    ].split(",")


def test_ehdb_helper_invocation_builds_playbook_plan():
    invocation = ehdb_helper_invocation_from_env(
        {
            EHDB_ENABLED_ENV: "1",
            EHDB_CLIENT_ROLE_ENV: "playbook",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "var/noetl/ehdb/reference.jsonl",
            EHDB_HELPER_BIN_ENV: "ehdb-local-reference",
        },
        args=("scan",),
    )

    assert invocation is not None
    assert invocation.argv == ("ehdb-local-reference", "scan")
    assert invocation.role is EhdbClientRole.PLAYBOOK
    assert invocation.local_reference_log == Path("var/noetl/ehdb/reference.jsonl")


def test_ehdb_summary_invocation_uses_concrete_helper_command():
    invocation = ehdb_local_reference_summary_invocation_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            EHDB_HELPER_BIN_ENV: "ehdb-local-reference",
        }
    )

    assert invocation is not None
    assert invocation.argv == (
        "ehdb-local-reference",
        "summary",
        "--log",
        "/tmp/noetl-ehdb.jsonl",
    )


def test_ehdb_summary_invocation_discovers_helper_from_path(tmp_path):
    helper = _helper_script(
        tmp_path,
        """
print("{}")
""",
        name=EHDB_LOCAL_REFERENCE_HELPER_NAME,
    )
    invocation = ehdb_local_reference_summary_invocation_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            "PATH": str(tmp_path),
        }
    )

    assert invocation is not None
    assert invocation.argv == (
        str(helper),
        "summary",
        "--log",
        "/tmp/noetl-ehdb.jsonl",
    )


def test_ehdb_summary_invocation_prefers_explicit_helper_over_path(tmp_path):
    _helper_script(
        tmp_path,
        """
print("{}")
""",
        name=EHDB_LOCAL_REFERENCE_HELPER_NAME,
    )
    invocation = ehdb_local_reference_summary_invocation_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            EHDB_HELPER_BIN_ENV: "/custom/ehdb-local-reference",
            "PATH": str(tmp_path),
        }
    )

    assert invocation is not None
    assert invocation.executable == "/custom/ehdb-local-reference"


def test_ehdb_helper_discovery_uses_candidate_paths(tmp_path):
    helper = _helper_script(
        tmp_path,
        """
print("{}")
""",
        name=EHDB_LOCAL_REFERENCE_HELPER_NAME,
    )

    assert discover_ehdb_helper_executable(
        {"PATH": ""},
        candidates=(tmp_path / "missing", helper),
        include_default_candidates=False,
    ) == str(helper)


def test_ehdb_helper_discovery_returns_none_when_missing(tmp_path):
    assert (
        discover_ehdb_helper_executable(
            {"PATH": str(tmp_path)},
            candidates=(),
            include_default_candidates=False,
        )
        is None
    )


def test_ehdb_helper_invocation_merges_subprocess_env():
    invocation = ehdb_helper_invocation_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            EHDB_HELPER_BIN_ENV: "ehdb-local-reference",
        }
    )

    assert invocation is not None
    merged = invocation.subprocess_env(
        {
            "PATH": "/usr/bin",
            EHDB_ENABLED_ENV: "false",
        }
    )

    assert merged["PATH"] == "/usr/bin"
    assert merged[EHDB_ENABLED_ENV] == "true"
    assert merged[EHDB_CLIENT_ROLE_ENV] == "worker"
    assert EhdbCapability.STREAM_APPEND.value in merged[EHDB_CAPABILITIES_ENV].split(",")
    assert merged[EHDB_LOCAL_REFERENCE_LOG_ENV] == "/tmp/noetl-ehdb.jsonl"


def test_execute_ehdb_local_reference_summary_decodes_json(tmp_path):
    helper = _helper_script(
        tmp_path,
        """
import json
import os
import sys

expected_log = os.environ["NOETL_EHDB_LOCAL_REFERENCE_LOG"]
if sys.argv[1:] != ["summary", "--log", expected_log]:
    print("unexpected argv", file=sys.stderr)
    sys.exit(4)
print(json.dumps({"transaction_count": 2, "stream_count": 1}))
""",
    )

    execution = execute_ehdb_local_reference_summary_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(tmp_path / "ehdb.jsonl"),
            EHDB_HELPER_BIN_ENV: str(helper),
        },
        base_env={"PATH": "/usr/bin"},
    )

    assert isinstance(execution, LocalReferenceEhdbExecution)
    assert execution.returncode == 0
    assert execution.json_payload == {"transaction_count": 2, "stream_count": 1}
    assert execution.invocation.argv == (
        str(helper),
        "summary",
        "--log",
        str(tmp_path / "ehdb.jsonl"),
    )


def test_read_ehdb_local_reference_summary_returns_typed_summary(tmp_path):
    log_path = tmp_path / "ehdb.jsonl"
    helper = _summary_helper(tmp_path)

    summary = read_ehdb_local_reference_summary_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(log_path),
            EHDB_HELPER_BIN_ENV: str(helper),
        },
        base_env={"PATH": "/usr/bin"},
    )

    assert isinstance(summary, LocalReferenceEhdbSummary)
    assert summary.log_path == log_path
    assert summary.counts["transaction_count"] == 3
    assert summary.counts["storage_replica_count"] == 0
    assert summary.as_dict()["log_path"] == str(log_path)


def test_read_ehdb_local_reference_summary_returns_none_when_disabled():
    assert read_ehdb_local_reference_summary_from_env({}) is None


def test_local_reference_summary_rejects_missing_required_fields():
    with pytest.raises(ValueError, match="missing required fields"):
        LocalReferenceEhdbSummary.from_payload({"log_path": "/tmp/ehdb.jsonl"})


def test_local_reference_summary_rejects_unexpected_log_path():
    payload = _summary_payload("/tmp/actual-ehdb.jsonl")

    with pytest.raises(ValueError, match="log_path does not match"):
        LocalReferenceEhdbSummary.from_payload(
            payload,
            expected_log="/tmp/expected-ehdb.jsonl",
        )


def test_local_reference_summary_rejects_non_integer_count():
    payload = _summary_payload("/tmp/ehdb.jsonl")
    payload["transaction_count"] = "1"

    with pytest.raises(ValueError, match="transaction_count must be an integer"):
        LocalReferenceEhdbSummary.from_payload(payload)


def test_local_reference_summary_rejects_negative_count():
    payload = _summary_payload("/tmp/ehdb.jsonl")
    payload["stream_count"] = -1

    with pytest.raises(ValueError, match="stream_count must be non-negative"):
        LocalReferenceEhdbSummary.from_payload(payload)


def test_execute_ehdb_helper_json_returns_none_when_disabled():
    assert execute_ehdb_local_reference_summary_from_env({}) is None


def test_execute_ehdb_helper_json_rejects_gateway_role():
    with pytest.raises(ValueError, match="gateway remains a gatekeeper"):
        execute_ehdb_local_reference_summary_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "gateway",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
                EHDB_HELPER_BIN_ENV: "ehdb-local-reference",
            }
        )


def test_execute_ehdb_helper_json_raises_on_nonzero_exit(tmp_path):
    helper = _helper_script(
        tmp_path,
        """
import sys

print("helper failed", file=sys.stderr)
sys.exit(7)
""",
    )
    invocation = LocalReferenceEhdbInvocation(
        executable=str(helper),
        args=("summary", "--log", str(tmp_path / "ehdb.jsonl")),
        env_items=(),
        role=EhdbClientRole.WORKER,
        local_reference_log=tmp_path / "ehdb.jsonl",
    )

    with pytest.raises(RuntimeError, match="exited with 7"):
        execute_ehdb_helper_json(invocation)


def test_execute_ehdb_helper_json_raises_on_timeout(tmp_path):
    helper = _helper_script(
        tmp_path,
        """
import time

time.sleep(2)
""",
    )
    invocation = LocalReferenceEhdbInvocation(
        executable=str(helper),
        args=("summary", "--log", str(tmp_path / "ehdb.jsonl")),
        env_items=(),
        role=EhdbClientRole.WORKER,
        local_reference_log=tmp_path / "ehdb.jsonl",
    )

    with pytest.raises(TimeoutError, match="timed out"):
        execute_ehdb_helper_json(invocation, timeout_seconds=0.01)


def test_execute_ehdb_helper_json_rejects_non_object_json(tmp_path):
    helper = _helper_script(
        tmp_path,
        """
print("[1, 2, 3]")
""",
    )
    invocation = LocalReferenceEhdbInvocation(
        executable=str(helper),
        args=("summary", "--log", str(tmp_path / "ehdb.jsonl")),
        env_items=(),
        role=EhdbClientRole.WORKER,
        local_reference_log=tmp_path / "ehdb.jsonl",
    )

    with pytest.raises(ValueError, match="JSON object"):
        execute_ehdb_helper_json(invocation)


def test_ehdb_helper_invocation_requires_explicit_helper_executable():
    with pytest.raises(ValueError, match=EHDB_HELPER_BIN_ENV):
        ehdb_helper_invocation_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "worker",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )


def test_ehdb_helper_invocation_rejects_blank_helper_args():
    adapter = ehdb_adapter_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
        }
    )

    assert adapter is not None
    with pytest.raises(ValueError, match="EHDB helper arg 1"):
        adapter.helper_invocation(
            executable="ehdb-local-reference",
            args=("scan", " "),
        )


def test_ehdb_adapter_rejects_gateway_role_via_contract():
    with pytest.raises(ValueError, match="gateway remains a gatekeeper"):
        ehdb_adapter_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "gateway",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )


def test_ehdb_helper_invocation_rejects_gateway_role_via_contract():
    with pytest.raises(ValueError, match="gateway remains a gatekeeper"):
        ehdb_helper_invocation_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "gateway",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
                EHDB_HELPER_BIN_ENV: "ehdb-local-reference",
            }
        )


def test_local_reference_adapter_requires_local_reference_contract():
    contract = ehdb_integration_contract_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
        }
    )

    adapter = LocalReferenceEhdbAdapter.from_contract(contract)

    assert adapter.runtime_env()[EHDB_MODE_ENV] == "local_reference"


def _helper_script(
    tmp_path: Path,
    body: str,
    *,
    name: str = "ehdb-helper.py",
) -> Path:
    helper = tmp_path / name
    helper.write_text(f"#!{sys.executable}\n{body.lstrip()}", encoding="utf-8")
    helper.chmod(0o755)
    return helper


def _summary_helper(tmp_path: Path) -> Path:
    payload = _summary_payload("placeholder")
    return _helper_script(
        tmp_path,
        f"""
import json
import sys

payload = {payload!r}
payload["log_path"] = sys.argv[3]
print(json.dumps(payload))
""",
    )


def _summary_payload(log_path: str) -> dict[str, int | str]:
    payload = {
        field: 0
        for field in EHDB_LOCAL_REFERENCE_SUMMARY_FIELDS
        if field != "log_path"
    }
    payload["log_path"] = log_path
    payload["transaction_count"] = 3
    return payload
