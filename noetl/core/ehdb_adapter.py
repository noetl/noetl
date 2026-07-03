"""Side-effect-free EHDB adapter factory for NoETL workers/playbooks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from noetl.core.ehdb_contract import (
    EHDB_CLIENT_ROLE_ENV,
    EHDB_ENABLED_ENV,
    EHDB_LOCAL_REFERENCE_LOG_ENV,
    EHDB_MODE_ENV,
    EhdbClientRole,
    EhdbIntegrationContract,
    EhdbIntegrationMode,
    ehdb_integration_contract_from_env,
    validate_ehdb_integration_contract,
)


@dataclass(frozen=True)
class LocalReferenceEhdbAdapter:
    """Adapter descriptor for EHDB local-reference worker/playbook usage."""

    contract: EhdbIntegrationContract

    @classmethod
    def from_contract(
        cls,
        contract: EhdbIntegrationContract,
    ) -> "LocalReferenceEhdbAdapter":
        validate_ehdb_integration_contract(contract)
        if contract.mode is not EhdbIntegrationMode.LOCAL_REFERENCE:
            raise ValueError("local-reference adapter requires local_reference mode")
        if contract.role not in {EhdbClientRole.WORKER, EhdbClientRole.PLAYBOOK}:
            raise ValueError("local-reference adapter requires worker or playbook role")
        return cls(contract=contract)

    @property
    def role(self) -> EhdbClientRole:
        return self.contract.role

    @property
    def local_reference_log(self) -> Path:
        if self.contract.local_reference_log is None:
            raise ValueError("local-reference adapter requires an event-log path")
        return self.contract.local_reference_log

    def runtime_env(self) -> dict[str, str]:
        """Return env vars a worker/playbook step can pass to EHDB helpers."""

        return {
            EHDB_ENABLED_ENV: "true",
            EHDB_MODE_ENV: EhdbIntegrationMode.LOCAL_REFERENCE.value,
            EHDB_CLIENT_ROLE_ENV: self.role.value,
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(self.local_reference_log),
        }


def ehdb_adapter_from_env(
    env: Mapping[str, str] | None = None,
) -> LocalReferenceEhdbAdapter | None:
    """Return the configured EHDB adapter, or None when EHDB is disabled."""

    contract = ehdb_integration_contract_from_env(os.environ if env is None else env)
    if not contract.enabled:
        return None
    return LocalReferenceEhdbAdapter.from_contract(contract)

