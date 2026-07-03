from pathlib import Path

import pytest

from noetl.core.ehdb_adapter import (
    EHDB_HELPER_BIN_ENV,
    LocalReferenceEhdbAdapter,
    LocalReferenceEhdbInvocation,
    ehdb_adapter_from_env,
    ehdb_helper_invocation_from_env,
)
from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
    EhdbClientRole,
    EhdbIntegrationMode,
    ehdb_integration_contract_from_env,
)


def test_ehdb_adapter_returns_none_when_disabled():
    assert ehdb_adapter_from_env({}) is None


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
    assert adapter.runtime_env() == {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: EhdbIntegrationMode.LOCAL_REFERENCE.value,
        EHDB_CLIENT_ROLE_ENV: EhdbClientRole.WORKER.value,
        EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
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
        EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
    }


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
    assert merged[EHDB_LOCAL_REFERENCE_LOG_ENV] == "/tmp/noetl-ehdb.jsonl"


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
