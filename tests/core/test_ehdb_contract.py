from pathlib import Path

import pytest

from noetl.core.ehdb_contract import (
    EHDB_CAPABILITIES_ENV,
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
    NOETL_RUN_MODE_ENV,
    EhdbCapability,
    EhdbClientRole,
    EhdbIntegrationMode,
    ehdb_integration_contract_from_env,
)


def test_ehdb_contract_is_disabled_by_default():
    contract = ehdb_integration_contract_from_env({})

    assert contract.enabled is False
    assert contract.mode is EhdbIntegrationMode.DISABLED
    assert contract.role is EhdbClientRole.WORKER
    assert contract.capabilities == frozenset()
    assert contract.local_reference_log is None
    assert contract.uses_local_reference_runtime is False
    assert contract.uses_control_plane_embedding is False


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
    assert EhdbCapability.TRANSACTION_APPEND in contract.capabilities
    assert contract.allows_capability(EhdbCapability.STREAM_APPEND)
    assert contract.local_reference_log == Path("/tmp/noetl-ehdb.jsonl")
    assert contract.uses_local_reference_runtime is True
    assert contract.uses_control_plane_embedding is False


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


@pytest.mark.parametrize("role", ["gateway", "api", "server"])
def test_ehdb_contract_accepts_control_plane_embedding_for_gatekeeper_roles(role):
    contract = ehdb_integration_contract_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            EHDB_CLIENT_ROLE_ENV: role,
        }
    )

    assert contract.enabled is True
    assert contract.mode is EhdbIntegrationMode.CONTROL_PLANE
    assert contract.role.value == role
    assert contract.capabilities == frozenset({EhdbCapability.CONTROL_PLANE})
    assert contract.local_reference_log is None
    assert contract.uses_control_plane_embedding is True
    assert contract.uses_local_reference_runtime is False


def test_ehdb_contract_accepts_server_run_mode_for_control_plane_embedding():
    contract = ehdb_integration_contract_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            NOETL_RUN_MODE_ENV: "server",
        }
    )

    assert contract.role is EhdbClientRole.SERVER
    assert contract.uses_control_plane_embedding is True


@pytest.mark.parametrize("role", ["gateway", "api", "server"])
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


def test_ehdb_contract_rejects_control_plane_data_capabilities():
    with pytest.raises(ValueError, match="only allows control_plane capability"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_MODE_ENV: "control_plane",
                EHDB_CLIENT_ROLE_ENV: "gateway",
                EHDB_CAPABILITIES_ENV: "control_plane,catalog_read",
            }
        )


def test_ehdb_contract_rejects_control_plane_local_reference_log():
    with pytest.raises(ValueError, match=EHDB_LOCAL_REFERENCE_LOG_ENV):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_MODE_ENV: "control_plane",
                EHDB_CLIENT_ROLE_ENV: "api",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )


def test_ehdb_contract_rejects_worker_control_plane_embedding():
    with pytest.raises(ValueError, match="gateway/api/server"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_MODE_ENV: "control_plane",
                EHDB_CLIENT_ROLE_ENV: "worker",
            }
        )


def test_ehdb_contract_accepts_explicit_local_reference_capabilities():
    contract = ehdb_integration_contract_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_CAPABILITIES_ENV: "catalog_read,transaction_append",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
        }
    )

    assert contract.capabilities == frozenset(
        {EhdbCapability.CATALOG_READ, EhdbCapability.TRANSACTION_APPEND}
    )


def test_ehdb_contract_rejects_local_reference_control_plane_capability():
    with pytest.raises(ValueError, match="requires data-plane capabilities"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "worker",
                EHDB_CAPABILITIES_ENV: "control_plane",
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

    with pytest.raises(ValueError, match="unsupported EHDB capability"):
        ehdb_integration_contract_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "worker",
                EHDB_CAPABILITIES_ENV: "gateway_data_read",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )
