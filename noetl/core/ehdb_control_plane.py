"""Side-effect-free EHDB control-plane embedding descriptor for NoETL."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from noetl.core.ehdb_contract import (
    EHDB_CAPABILITIES_ENV,
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_MODE_ENV,
    EhdbCapability,
    EhdbClientRole,
    EhdbIntegrationContract,
    EhdbIntegrationMode,
    ehdb_integration_contract_from_env,
    validate_ehdb_integration_contract,
)


@dataclass(frozen=True)
class ControlPlaneEhdbEmbedding:
    """Planning-only descriptor for EHDB embedded in gateway/API/server roles."""

    contract: EhdbIntegrationContract

    @classmethod
    def from_contract(
        cls,
        contract: EhdbIntegrationContract,
    ) -> "ControlPlaneEhdbEmbedding":
        validate_ehdb_integration_contract(contract)
        if contract.mode is not EhdbIntegrationMode.CONTROL_PLANE:
            raise ValueError("control-plane descriptor requires control_plane mode")
        if contract.capabilities != frozenset({EhdbCapability.CONTROL_PLANE}):
            raise ValueError(
                "control-plane descriptor requires control_plane capability only"
            )
        if contract.role not in {
            EhdbClientRole.GATEWAY,
            EhdbClientRole.API,
            EhdbClientRole.SERVER,
        }:
            raise ValueError(
                "control-plane descriptor requires gateway, api, or server role"
            )
        return cls(contract=contract)

    @property
    def role(self) -> EhdbClientRole:
        return self.contract.role

    @property
    def capabilities(self) -> frozenset[EhdbCapability]:
        return self.contract.capabilities

    def runtime_env(self) -> dict[str, str]:
        """Return env vars that preserve control-plane-only embedding."""

        return {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: EhdbIntegrationMode.CONTROL_PLANE.value,
            EHDB_CLIENT_ROLE_ENV: self.role.value,
            EHDB_CAPABILITIES_ENV: EhdbCapability.CONTROL_PLANE.value,
        }


def ehdb_control_plane_from_env(
    env: Mapping[str, str] | None = None,
) -> ControlPlaneEhdbEmbedding | None:
    """Return the configured EHDB control-plane descriptor, or None."""

    contract = ehdb_integration_contract_from_env(os.environ if env is None else env)
    if not contract.enabled:
        return None
    if contract.mode is not EhdbIntegrationMode.CONTROL_PLANE:
        return None
    return ControlPlaneEhdbEmbedding.from_contract(contract)
