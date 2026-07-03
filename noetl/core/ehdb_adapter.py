"""Side-effect-free EHDB adapter factory for NoETL workers/playbooks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from noetl.core.ehdb_contract import (
    EHDB_CAPABILITIES_ENV,
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


EHDB_HELPER_BIN_ENV = "NOETL_EHDB_HELPER_BIN"


@dataclass(frozen=True)
class LocalReferenceEhdbInvocation:
    """Immutable invocation plan for a future EHDB local-reference helper."""

    executable: str
    args: tuple[str, ...]
    env_items: tuple[tuple[str, str], ...]
    role: EhdbClientRole
    local_reference_log: Path

    @property
    def argv(self) -> tuple[str, ...]:
        return (self.executable, *self.args)

    @property
    def env(self) -> dict[str, str]:
        return dict(self.env_items)

    def subprocess_env(
        self,
        base_env: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        env = dict(base_env or {})
        env.update(self.env)
        return env


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
            EHDB_CAPABILITIES_ENV: ",".join(
                sorted(capability.value for capability in self.contract.capabilities)
            ),
            EHDB_LOCAL_REFERENCE_LOG_ENV: str(self.local_reference_log),
        }

    def helper_invocation(
        self,
        *,
        executable: str,
        args: Sequence[str] = (),
    ) -> LocalReferenceEhdbInvocation:
        """Return a subprocess invocation plan without executing it."""

        helper_executable = _non_empty_text(executable, "EHDB helper executable")
        helper_args = tuple(
            _non_empty_text(arg, f"EHDB helper arg {index}")
            for index, arg in enumerate(args)
        )
        runtime_env = self.runtime_env()
        return LocalReferenceEhdbInvocation(
            executable=helper_executable,
            args=helper_args,
            env_items=tuple(runtime_env.items()),
            role=self.role,
            local_reference_log=self.local_reference_log,
        )


def ehdb_adapter_from_env(
    env: Mapping[str, str] | None = None,
) -> LocalReferenceEhdbAdapter | None:
    """Return the configured EHDB adapter, or None when EHDB is disabled."""

    contract = ehdb_integration_contract_from_env(os.environ if env is None else env)
    if not contract.enabled:
        return None
    if contract.mode is not EhdbIntegrationMode.LOCAL_REFERENCE:
        return None
    return LocalReferenceEhdbAdapter.from_contract(contract)


def ehdb_helper_invocation_from_env(
    env: Mapping[str, str] | None = None,
    *,
    args: Sequence[str] = (),
) -> LocalReferenceEhdbInvocation | None:
    """Return a configured EHDB helper invocation plan, or None when disabled."""

    source_env = os.environ if env is None else env
    adapter = ehdb_adapter_from_env(source_env)
    if adapter is None:
        return None
    executable = _non_empty_text(
        source_env.get(EHDB_HELPER_BIN_ENV),
        EHDB_HELPER_BIN_ENV,
    )
    return adapter.helper_invocation(executable=executable, args=args)


def _non_empty_text(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()
