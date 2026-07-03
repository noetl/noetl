"""Feature-gated EHDB integration contract for NoETL.

This module is intentionally side-effect free. It only validates the
NoETL execution-model boundary for future EHDB wiring; it does not
connect to EHDB, open files, or replace any existing storage backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Mapping


EHDB_ENABLED_ENV = "NOETL_EHDB_ENABLED"
EHDB_MODE_ENV = "NOETL_EHDB_MODE"
EHDB_CLIENT_ROLE_ENV = "NOETL_EHDB_CLIENT_ROLE"
EHDB_CAPABILITIES_ENV = "NOETL_EHDB_CAPABILITIES"
EHDB_LOCAL_REFERENCE_LOG_ENV = "NOETL_EHDB_LOCAL_REFERENCE_LOG"
NOETL_RUN_MODE_ENV = "NOETL_RUN_MODE"


class EhdbIntegrationMode(StrEnum):
    DISABLED = "disabled"
    CONTROL_PLANE = "control_plane"
    LOCAL_REFERENCE = "local_reference"


class EhdbClientRole(StrEnum):
    GATEWAY = "gateway"
    API = "api"
    SERVER = "server"
    WORKER = "worker"
    PLAYBOOK = "playbook"
    SYSTEM = "system"


class EhdbCapability(StrEnum):
    CONTROL_PLANE = "control_plane"
    CATALOG_READ = "catalog_read"
    CATALOG_WRITE = "catalog_write"
    TRANSACTION_APPEND = "transaction_append"
    STREAM_APPEND = "stream_append"
    STREAM_CONSUME = "stream_consume"
    OBJECT_READ = "object_read"
    OBJECT_WRITE = "object_write"
    RETRIEVAL_READ = "retrieval_read"
    RETRIEVAL_WRITE = "retrieval_write"
    REPLICATION_PLAN = "replication_plan"
    SYSTEM_LIBRARY_RESOLVE = "system_library_resolve"


_CONTROL_PLANE_ROLES = {
    EhdbClientRole.GATEWAY,
    EhdbClientRole.API,
    EhdbClientRole.SERVER,
}
_LOCAL_REFERENCE_ROLES = {
    EhdbClientRole.WORKER,
    EhdbClientRole.PLAYBOOK,
    EhdbClientRole.SYSTEM,
}
_DATA_PLANE_CAPABILITIES = frozenset(
    capability
    for capability in EhdbCapability
    if capability is not EhdbCapability.CONTROL_PLANE
)


@dataclass(frozen=True)
class EhdbIntegrationContract:
    enabled: bool
    mode: EhdbIntegrationMode
    role: EhdbClientRole
    capabilities: frozenset[EhdbCapability]
    local_reference_log: Path | None = None

    @property
    def uses_local_reference_runtime(self) -> bool:
        return self.enabled and self.mode is EhdbIntegrationMode.LOCAL_REFERENCE

    @property
    def uses_control_plane_embedding(self) -> bool:
        return self.enabled and self.mode is EhdbIntegrationMode.CONTROL_PLANE

    def allows_capability(self, capability: EhdbCapability) -> bool:
        return capability in self.capabilities


def ehdb_integration_contract_from_env(
    env: Mapping[str, str],
) -> EhdbIntegrationContract:
    """Build and validate the disabled-by-default EHDB contract."""

    enabled = _truthy(env.get(EHDB_ENABLED_ENV))
    role = _client_role(env)
    mode = _integration_mode(env, enabled=enabled)
    capabilities = _capabilities(env, enabled=enabled, mode=mode)
    local_reference_log = _path_or_none(env.get(EHDB_LOCAL_REFERENCE_LOG_ENV))

    contract = EhdbIntegrationContract(
        enabled=enabled,
        mode=mode,
        role=role,
        capabilities=capabilities,
        local_reference_log=local_reference_log,
    )
    validate_ehdb_integration_contract(contract)
    return contract


def validate_ehdb_integration_contract(
    contract: EhdbIntegrationContract,
) -> EhdbIntegrationContract:
    if not contract.enabled:
        if contract.mode is not EhdbIntegrationMode.DISABLED:
            raise ValueError("disabled EHDB integration must use disabled mode")
        if contract.capabilities:
            raise ValueError("disabled EHDB integration must not declare capabilities")
        return contract

    if contract.mode is EhdbIntegrationMode.CONTROL_PLANE:
        if contract.role not in _CONTROL_PLANE_ROLES:
            raise ValueError(
                "EHDB control-plane embedding is only supported for "
                "gateway/api/server roles"
            )
        if contract.capabilities != frozenset({EhdbCapability.CONTROL_PLANE}):
            raise ValueError(
                "EHDB control-plane embedding only allows control_plane capability"
            )
        if contract.local_reference_log is not None:
            raise ValueError(
                "EHDB control-plane embedding must not define "
                "NOETL_EHDB_LOCAL_REFERENCE_LOG"
            )
        return contract

    if contract.role in _CONTROL_PLANE_ROLES:
        raise ValueError(
            "EHDB data-plane integration may not run in gateway/api/server "
            "roles; gateway remains a gatekeeper and must not touch data directly"
        )

    if contract.mode is not EhdbIntegrationMode.LOCAL_REFERENCE:
        raise ValueError(
            "enabled EHDB integration currently supports control_plane "
            "or local_reference mode only"
        )

    if contract.role not in _LOCAL_REFERENCE_ROLES:
        raise ValueError("EHDB local_reference mode requires worker/playbook/system role")

    if not contract.capabilities or EhdbCapability.CONTROL_PLANE in contract.capabilities:
        raise ValueError("EHDB local_reference mode requires data-plane capabilities")

    unsupported_capabilities = contract.capabilities - _DATA_PLANE_CAPABILITIES
    if unsupported_capabilities:
        raise ValueError(
            "EHDB local_reference mode received unsupported capabilities: "
            + ", ".join(sorted(capability.value for capability in unsupported_capabilities))
        )

    if contract.local_reference_log is None:
        raise ValueError(
            "NOETL_EHDB_LOCAL_REFERENCE_LOG is required for local_reference mode"
        )

    return contract


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _integration_mode(
    env: Mapping[str, str],
    *,
    enabled: bool,
) -> EhdbIntegrationMode:
    raw = env.get(EHDB_MODE_ENV)
    if raw is None or not raw.strip():
        return (
            EhdbIntegrationMode.LOCAL_REFERENCE
            if enabled
            else EhdbIntegrationMode.DISABLED
        )
    try:
        return EhdbIntegrationMode(raw.strip().lower())
    except ValueError as exc:
        raise ValueError(f"unsupported EHDB integration mode: {raw}") from exc


def _capabilities(
    env: Mapping[str, str],
    *,
    enabled: bool,
    mode: EhdbIntegrationMode,
) -> frozenset[EhdbCapability]:
    raw = env.get(EHDB_CAPABILITIES_ENV)
    if not enabled:
        if raw is not None and raw.strip():
            raise ValueError("disabled EHDB integration must not declare capabilities")
        return frozenset()
    if raw is None or not raw.strip():
        if mode is EhdbIntegrationMode.CONTROL_PLANE:
            return frozenset({EhdbCapability.CONTROL_PLANE})
        if mode is EhdbIntegrationMode.LOCAL_REFERENCE:
            return _DATA_PLANE_CAPABILITIES
        return frozenset()

    capabilities: set[EhdbCapability] = set()
    for token in raw.split(","):
        normalized = token.strip().lower()
        if not normalized:
            raise ValueError("empty EHDB capability token")
        try:
            capabilities.add(EhdbCapability(normalized))
        except ValueError as exc:
            raise ValueError(f"unsupported EHDB capability: {token}") from exc
    return frozenset(capabilities)


def _client_role(env: Mapping[str, str]) -> EhdbClientRole:
    raw = env.get(EHDB_CLIENT_ROLE_ENV) or env.get(NOETL_RUN_MODE_ENV) or "worker"
    normalized = raw.strip().lower()
    if normalized == "server":
        return EhdbClientRole.SERVER
    try:
        return EhdbClientRole(normalized)
    except ValueError as exc:
        raise ValueError(f"unsupported EHDB client role: {raw}") from exc


def _path_or_none(value: str | None) -> Path | None:
    if value is None or not value.strip():
        return None
    return Path(value.strip())
