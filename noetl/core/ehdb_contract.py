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
EHDB_LOCAL_REFERENCE_LOG_ENV = "NOETL_EHDB_LOCAL_REFERENCE_LOG"
NOETL_RUN_MODE_ENV = "NOETL_RUN_MODE"


class EhdbIntegrationMode(StrEnum):
    DISABLED = "disabled"
    LOCAL_REFERENCE = "local_reference"


class EhdbClientRole(StrEnum):
    GATEWAY = "gateway"
    SERVER = "server"
    WORKER = "worker"
    PLAYBOOK = "playbook"


@dataclass(frozen=True)
class EhdbIntegrationContract:
    enabled: bool
    mode: EhdbIntegrationMode
    role: EhdbClientRole
    local_reference_log: Path | None = None

    @property
    def uses_local_reference_runtime(self) -> bool:
        return self.enabled and self.mode is EhdbIntegrationMode.LOCAL_REFERENCE


def ehdb_integration_contract_from_env(
    env: Mapping[str, str],
) -> EhdbIntegrationContract:
    """Build and validate the disabled-by-default EHDB contract."""

    enabled = _truthy(env.get(EHDB_ENABLED_ENV))
    role = _client_role(env)
    mode = _integration_mode(env, enabled=enabled)
    local_reference_log = _path_or_none(env.get(EHDB_LOCAL_REFERENCE_LOG_ENV))

    contract = EhdbIntegrationContract(
        enabled=enabled,
        mode=mode,
        role=role,
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
        return contract

    if contract.role in {EhdbClientRole.GATEWAY, EhdbClientRole.SERVER}:
        raise ValueError(
            "EHDB integration may not run in gateway/server roles; "
            "gateway remains a gatekeeper and must not touch data directly"
        )

    if contract.mode is not EhdbIntegrationMode.LOCAL_REFERENCE:
        raise ValueError(
            "enabled EHDB integration currently supports local_reference only"
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
