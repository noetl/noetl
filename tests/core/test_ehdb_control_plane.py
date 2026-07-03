import pytest

from noetl.core.ehdb_control_plane import (
    ControlPlaneEhdbEmbedding,
    ehdb_control_plane_from_env,
)
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


def test_ehdb_control_plane_returns_none_when_disabled():
    assert ehdb_control_plane_from_env({}) is None


@pytest.mark.parametrize(
    ("role", "expected_role"),
    [
        ("gateway", EhdbClientRole.GATEWAY),
        ("api", EhdbClientRole.API),
        ("server", EhdbClientRole.SERVER),
    ],
)
def test_ehdb_control_plane_builds_gatekeeper_descriptor(role, expected_role):
    descriptor = ehdb_control_plane_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            EHDB_CLIENT_ROLE_ENV: role,
        }
    )

    assert isinstance(descriptor, ControlPlaneEhdbEmbedding)
    assert descriptor.role is expected_role
    assert descriptor.capabilities == frozenset({EhdbCapability.CONTROL_PLANE})


def test_ehdb_control_plane_accepts_server_run_mode():
    descriptor = ehdb_control_plane_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            NOETL_RUN_MODE_ENV: "server",
        }
    )

    assert descriptor is not None
    assert descriptor.role is EhdbClientRole.SERVER


def test_ehdb_control_plane_exports_runtime_env():
    descriptor = ehdb_control_plane_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            EHDB_CLIENT_ROLE_ENV: "gateway",
        }
    )

    assert descriptor is not None
    assert descriptor.runtime_env() == {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: EhdbIntegrationMode.CONTROL_PLANE.value,
        EHDB_CLIENT_ROLE_ENV: EhdbClientRole.GATEWAY.value,
        EHDB_CAPABILITIES_ENV: EhdbCapability.CONTROL_PLANE.value,
    }


def test_ehdb_control_plane_returns_none_for_local_reference():
    assert (
        ehdb_control_plane_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "worker",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )
        is None
    )


def test_ehdb_control_plane_rejects_data_plane_capabilities():
    with pytest.raises(ValueError, match="only allows control_plane capability"):
        ehdb_control_plane_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_MODE_ENV: "control_plane",
                EHDB_CLIENT_ROLE_ENV: "gateway",
                EHDB_CAPABILITIES_ENV: "control_plane,catalog_read",
            }
        )


def test_control_plane_descriptor_requires_control_plane_contract():
    contract = ehdb_integration_contract_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            EHDB_CLIENT_ROLE_ENV: "api",
        }
    )

    descriptor = ControlPlaneEhdbEmbedding.from_contract(contract)

    assert descriptor.runtime_env()[EHDB_CLIENT_ROLE_ENV] == "api"
