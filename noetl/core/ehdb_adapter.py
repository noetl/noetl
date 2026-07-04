"""Side-effect-free EHDB adapter factory for NoETL workers/playbooks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

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
EHDB_LOCAL_REFERENCE_HELPER_NAME = "ehdb-local-reference"


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
class LocalReferenceEhdbExecution:
    """Captured JSON result from a bounded EHDB helper execution."""

    invocation: LocalReferenceEhdbInvocation
    returncode: int
    stdout: str
    stderr: str
    json_payload: Mapping[str, Any]


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


def discover_ehdb_helper_executable(
    env: Mapping[str, str] | None = None,
    *,
    helper_name: str = EHDB_LOCAL_REFERENCE_HELPER_NAME,
    candidates: Sequence[Path | str] = (),
    include_default_candidates: bool = True,
) -> str | None:
    """Discover the EHDB helper binary without executing it."""

    source_env = os.environ if env is None else env
    explicit = source_env.get(EHDB_HELPER_BIN_ENV)
    if explicit is not None:
        return _non_empty_text(explicit, EHDB_HELPER_BIN_ENV)

    found = shutil.which(helper_name, path=source_env.get("PATH"))
    if found:
        return found

    helper_candidates = [Path(candidate) for candidate in candidates]
    if include_default_candidates:
        helper_candidates.extend(_default_ehdb_helper_candidates(helper_name))
    for candidate in helper_candidates:
        if _is_executable_file(candidate):
            return str(candidate)
    return None


def ehdb_local_reference_summary_invocation_from_env(
    env: Mapping[str, str] | None = None,
) -> LocalReferenceEhdbInvocation | None:
    """Return the concrete local-reference summary helper invocation."""

    source_env = os.environ if env is None else env
    adapter = ehdb_adapter_from_env(source_env)
    if adapter is None:
        return None
    executable = discover_ehdb_helper_executable(source_env)
    if executable is None:
        raise ValueError(
            f"{EHDB_HELPER_BIN_ENV} is required or "
            f"{EHDB_LOCAL_REFERENCE_HELPER_NAME} must be discoverable"
        )
    return adapter.helper_invocation(
        executable=executable,
        args=("summary", "--log", str(adapter.local_reference_log)),
    )


def execute_ehdb_helper_json(
    invocation: LocalReferenceEhdbInvocation,
    *,
    timeout_seconds: float = 30.0,
    base_env: Mapping[str, str] | None = None,
) -> LocalReferenceEhdbExecution:
    """Execute a bounded EHDB helper and decode a JSON object from stdout."""

    if timeout_seconds <= 0:
        raise ValueError("EHDB helper timeout must be positive")

    try:
        completed = subprocess.run(
            invocation.argv,
            check=False,
            capture_output=True,
            text=True,
            env=invocation.subprocess_env(base_env),
            timeout=timeout_seconds,
        )
    except FileNotFoundError as exc:
        raise ValueError(f"EHDB helper executable not found: {invocation.executable}") from exc
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError(
            f"EHDB helper timed out after {timeout_seconds:g}s: {invocation.executable}"
        ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            f"EHDB helper exited with {completed.returncode}: {completed.stderr.strip()}"
        )

    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError("EHDB helper stdout was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("EHDB helper stdout must decode to a JSON object")

    return LocalReferenceEhdbExecution(
        invocation=invocation,
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        json_payload=payload,
    )


def execute_ehdb_local_reference_summary_from_env(
    env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float = 30.0,
    base_env: Mapping[str, str] | None = None,
) -> LocalReferenceEhdbExecution | None:
    """Execute the configured local-reference summary helper, if enabled."""

    invocation = ehdb_local_reference_summary_invocation_from_env(env)
    if invocation is None:
        return None
    return execute_ehdb_helper_json(
        invocation,
        timeout_seconds=timeout_seconds,
        base_env=base_env,
    )


def _non_empty_text(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _default_ehdb_helper_candidates(helper_name: str) -> tuple[Path, ...]:
    repo_root = Path(__file__).resolve().parents[2]
    repos_root = repo_root.parent
    return (
        Path("/usr/local/bin") / helper_name,
        Path("/opt/noetl/bin") / helper_name,
        repos_root / "ehdb" / "target" / "release" / helper_name,
        repos_root / "ehdb" / "target" / "debug" / helper_name,
    )


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)
