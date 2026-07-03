from pathlib import Path

import pytest

from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
    NOETL_RUN_MODE_ENV,
    EhdbClientRole,
    EhdbIntegrationMode,
    ehdb_integration_contract_from_env,
)


def test_ehdb_contract_is_disabled_by_default():
    contract = ehdb_integration_contract_from_env({})

    assert contract.enabled is False
    assert contract.mode is EhdbIntegrationMode.DISABLED
    assert contract.role is EhdbClientRole.WORKER
    assert contract.local_reference_log is None
    assert contract.uses_local_reference_runtime is False


def test_ehdb_contract_accepts_worker_local_reference_mode():
    contract = ehdb_integration_contract_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
        }
    )

    assert contract.enabled is True
    assert contract.mode is EhdbIntegrationMode.LOCAL_REFERENCE
    assert contract.role is EhdbClientRole.WORKER
    assert contract.local_reference_log == Path("/tmp/noetl-ehdb.jsonl")
    assert contract.uses_local_reference_runtime is True


def test_ehdb_contract_accepts_playbook_local_reference_mode():
    contract = ehdb_integration_contract_from_env(
        {
            EHDB_ENABLED_ENV: "1",
            EHDB_MODE_ENV: "local_reference",
            EHDB_CLIENT_ROLE_ENV: "playbook",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "var/noetl/ehdb/reference.jsonl",
        }
    )

    assert contract.role is EhdbClientRole.PLAYBOOK
    assert contract.local_reference_log == Path("var/noetl/ehdb/reference.jsonl")


@pytest.mark.parametrize("role", ["gateway", "server"])
def test_ehdb_contract_rejects_gateway_and_server_data_touch_roles(role):
    with pytest.raises(ValueError, match="gateway remains a gatekeeper"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: role,
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )


def test_ehdb_contract_rejects_server_run_mode_when_role_is_not_overridden():
    with pytest.raises(ValueError, match="gateway remains a gatekeeper"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                NOETL_RUN_MODE_ENV: "server",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )


def test_ehdb_contract_requires_explicit_local_reference_log_when_enabled():
    with pytest.raises(ValueError, match=EHDB_LOCAL_REFERENCE_LOG_ENV):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "worker",
            }
        )


def test_ehdb_contract_rejects_unknown_mode_and_role():
    with pytest.raises(ValueError, match="unsupported EHDB integration mode"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_MODE_ENV: "flight",
                EHDB_CLIENT_ROLE_ENV: "worker",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )

    with pytest.raises(ValueError, match="unsupported EHDB client role"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "tenant-daemon",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )

