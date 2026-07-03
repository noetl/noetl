from pathlib import Path

import pytest

from noetl.core.ehdb_adapter import (
    LocalReferenceEhdbAdapter,
    ehdb_adapter_from_env,
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


def test_ehdb_adapter_rejects_gateway_role_via_contract():
    with pytest.raises(ValueError, match="gateway remains a gatekeeper"):
        ehdb_adapter_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "gateway",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
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

