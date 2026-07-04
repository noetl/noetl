"""Unified side-effect-free EHDB surface selector for NoETL."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from noetl.core.ehdb_adapter import LocalReferenceEhdbAdapter, ehdb_adapter_from_env
from noetl.core.ehdb_contract import (
    EhdbCapability,
    EhdbClientRole,
    EhdbIntegrationMode,
    ehdb_integration_contract_from_env,
)
from noetl.core.ehdb_control_plane import (
    ControlPlaneEhdbEmbedding,
    ehdb_control_plane_from_env,
)


@dataclass(frozen=True)
class EhdbIntegrationSurface:
    """Selected EHDB integration surface without performing data access."""

    surface: ControlPlaneEhdbEmbedding | LocalReferenceEhdbAdapter

    @property
    def mode(self) -> EhdbIntegrationMode:
        return self.surface.contract.mode

    @property
    def role(self) -> EhdbClientRole:
        return self.surface.role

    @property
    def capabilities(self) -> frozenset[EhdbCapability]:
        return self.surface.contract.capabilities

    @property
    def is_control_plane(self) -> bool:
        return isinstance(self.surface, ControlPlaneEhdbEmbedding)

    @property
    def is_local_reference(self) -> bool:
        return isinstance(self.surface, LocalReferenceEhdbAdapter)

    def runtime_env(self) -> dict[str, str]:
        return self.surface.runtime_env()


def ehdb_surface_from_env(
    env: Mapping[str, str] | None = None,
) -> EhdbIntegrationSurface | None:
    """Return the configured EHDB surface, or None when EHDB is disabled."""

    source_env = os.environ if env is None else env
    contract = ehdb_integration_contract_from_env(source_env)
    if not contract.enabled:
        return None

    if contract.mode is EhdbIntegrationMode.CONTROL_PLANE:
        surface = ehdb_control_plane_from_env(source_env)
    elif contract.mode is EhdbIntegrationMode.LOCAL_REFERENCE:
        surface = ehdb_adapter_from_env(source_env)
    else:
        surface = None

    if surface is None:
        return None
    return EhdbIntegrationSurface(surface=surface)
