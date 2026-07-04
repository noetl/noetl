import pytest

from noetl.core.ehdb_contract import (
    EHDB_CAPABILITIES_ENV,
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
    EhdbCapability,
    EhdbClientRole,
    EhdbIntegrationMode,
)
from noetl.core.ehdb_surface import EhdbIntegrationSurface, ehdb_surface_from_env


def test_ehdb_surface_returns_none_when_disabled():
    assert ehdb_surface_from_env({}) is None


def test_ehdb_surface_selects_control_plane_descriptor():
    surface = ehdb_surface_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: "control_plane",
            EHDB_CLIENT_ROLE_ENV: "gateway",
        }
    )

    assert isinstance(surface, EhdbIntegrationSurface)
    assert surface.is_control_plane is True
    assert surface.is_local_reference is False
    assert surface.mode is EhdbIntegrationMode.CONTROL_PLANE
    assert surface.role is EhdbClientRole.GATEWAY
    assert surface.capabilities == frozenset({EhdbCapability.CONTROL_PLANE})
    assert surface.runtime_env() == {
        EHDB_ENABLED_ENV: "true",
        EHDB_MODE_ENV: "control_plane",
        EHDB_CLIENT_ROLE_ENV: "gateway",
        EHDB_CAPABILITIES_ENV: "control_plane",
    }


def test_ehdb_surface_selects_local_reference_adapter():
    surface = ehdb_surface_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "worker",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
        }
    )

    assert isinstance(surface, EhdbIntegrationSurface)
    assert surface.is_control_plane is False
    assert surface.is_local_reference is True
    assert surface.mode is EhdbIntegrationMode.LOCAL_REFERENCE
    assert surface.role is EhdbClientRole.WORKER
    assert EhdbCapability.TRANSACTION_APPEND in surface.capabilities
    assert surface.runtime_env()[EHDB_LOCAL_REFERENCE_LOG_ENV] == "/tmp/noetl-ehdb.jsonl"


def test_ehdb_surface_preserves_explicit_local_reference_capabilities():
    surface = ehdb_surface_from_env(
        {
            EHDB_ENABLED_ENV: "true",
            EHDB_CLIENT_ROLE_ENV: "playbook",
            EHDB_CAPABILITIES_ENV: "catalog_read,transaction_append",
            EHDB_LOCAL_REFERENCE_LOG_ENV: "var/noetl/ehdb/reference.jsonl",
        }
    )

    assert surface is not None
    assert surface.capabilities == frozenset(
        {EhdbCapability.CATALOG_READ, EhdbCapability.TRANSACTION_APPEND}
    )
    assert surface.runtime_env()[EHDB_CAPABILITIES_ENV] == (
        "catalog_read,transaction_append"
    )


def test_ehdb_surface_rejects_gateway_local_reference_data_plane():
    with pytest.raises(ValueError, match="gateway remains a gatekeeper"):
        ehdb_surface_from_env(
            {
                EHDB_ENABLED_ENV: "true",
                EHDB_CLIENT_ROLE_ENV: "gateway",
                EHDB_LOCAL_REFERENCE_LOG_ENV: "/tmp/noetl-ehdb.jsonl",
            }
        )
