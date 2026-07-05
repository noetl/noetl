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
EHDB_LOCAL_REFERENCE_SUMMARY_FIELDS = (
    "log_path",
    "transaction_count",
    "table_count",
    "snapshot_count",
    "scan_grant_count",
    "stream_count",
    "stream_record_count",
    "stream_consumer_count",
    "retrieval_document_count",
    "retrieval_chunk_count",
    "retrieval_embedding_count",
    "system_library_count",
    "system_binding_count",
    "storage_object_count",
    "storage_replica_count",
)
_EHDB_LOCAL_REFERENCE_COUNT_FIELDS = tuple(
    field for field in EHDB_LOCAL_REFERENCE_SUMMARY_FIELDS if field != "log_path"
)


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
class LocalReferenceEhdbSummary:
    """Validated summary returned by `ehdb-local-reference summary`."""

    log_path: Path
    counts: Mapping[str, int]

    @classmethod
    def from_payload(
        cls,
        payload: Mapping[str, Any],
        *,
        expected_log: Path | str | None = None,
    ) -> "LocalReferenceEhdbSummary":
        missing = [
            field for field in EHDB_LOCAL_REFERENCE_SUMMARY_FIELDS if field not in payload
        ]
        if missing:
            raise ValueError(f"EHDB summary missing required fields: {', '.join(missing)}")

        log_path = _summary_log_path(payload["log_path"])
        if expected_log is not None and log_path != Path(expected_log):
            raise ValueError("EHDB summary log_path does not match requested log")

        counts: dict[str, int] = {}
        for field in _EHDB_LOCAL_REFERENCE_COUNT_FIELDS:
            counts[field] = _summary_count(payload[field], field)
        return cls(log_path=log_path, counts=counts)

    def as_dict(self) -> dict[str, int | str]:
        return {
            "log_path": str(self.log_path),
            **self.counts,
        }


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
        if contract.role not in {
            EhdbClientRole.WORKER,
            EhdbClientRole.PLAYBOOK,
            EhdbClientRole.SYSTEM,
        }:
            raise ValueError(
                "local-reference adapter requires worker, playbook, or system role"
            )
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


def read_ehdb_local_reference_summary_from_env(
    env: Mapping[str, str] | None = None,
    *,
    timeout_seconds: float = 30.0,
    base_env: Mapping[str, str] | None = None,
) -> LocalReferenceEhdbSummary | None:
    """Execute the summary helper and return a validated typed summary."""

    execution = execute_ehdb_local_reference_summary_from_env(
        env,
        timeout_seconds=timeout_seconds,
        base_env=base_env,
    )
    if execution is None:
        return None
    return LocalReferenceEhdbSummary.from_payload(
        execution.json_payload,
        expected_log=execution.invocation.local_reference_log,
    )


EHDB_LOCAL_REFERENCE_APPEND_FIELDS = (
    "action",
    "log_path",
    "tenant",
    "namespace",
    "stream",
    "subject",
    "sequence",
    "byte_len",
    "created_stream",
    "stream_record_count",
    "transaction_count",
)
EHDB_LOCAL_REFERENCE_READ_FIELDS = (
    "action",
    "log_path",
    "tenant",
    "namespace",
    "stream",
    "exists",
    "record_count",
    "returned",
    "records",
)


@dataclass(frozen=True)
class LocalReferenceAppendResult:
    """Validated result of a bounded ``append`` domain-record helper call."""

    log_path: Path
    tenant: str
    namespace: str
    stream: str
    subject: str
    sequence: int
    byte_len: int
    created_stream: bool
    stream_record_count: int
    transaction_count: int

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "LocalReferenceAppendResult":
        missing = [
            field for field in EHDB_LOCAL_REFERENCE_APPEND_FIELDS if field not in payload
        ]
        if missing:
            raise ValueError(
                f"EHDB append result missing required fields: {', '.join(missing)}"
            )
        if payload["action"] != "append":
            raise ValueError("EHDB append result action must be 'append'")
        return cls(
            log_path=_summary_log_path(payload["log_path"]),
            tenant=_result_text(payload["tenant"], "tenant"),
            namespace=_result_text(payload["namespace"], "namespace"),
            stream=_result_text(payload["stream"], "stream"),
            subject=_result_text(payload["subject"], "subject"),
            sequence=_summary_count(payload["sequence"], "sequence"),
            byte_len=_summary_count(payload["byte_len"], "byte_len"),
            created_stream=_result_bool(payload["created_stream"], "created_stream"),
            stream_record_count=_summary_count(
                payload["stream_record_count"], "stream_record_count"
            ),
            transaction_count=_summary_count(
                payload["transaction_count"], "transaction_count"
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": "append",
            "log_path": str(self.log_path),
            "tenant": self.tenant,
            "namespace": self.namespace,
            "stream": self.stream,
            "subject": self.subject,
            "sequence": self.sequence,
            "byte_len": self.byte_len,
            "created_stream": self.created_stream,
            "stream_record_count": self.stream_record_count,
            "transaction_count": self.transaction_count,
        }


@dataclass(frozen=True)
class LocalReferenceReadResult:
    """Validated result of a bounded ``read`` domain-record helper call."""

    log_path: Path
    tenant: str
    namespace: str
    stream: str
    exists: bool
    record_count: int
    returned: int
    records: tuple[Mapping[str, Any], ...]

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "LocalReferenceReadResult":
        missing = [
            field for field in EHDB_LOCAL_REFERENCE_READ_FIELDS if field not in payload
        ]
        if missing:
            raise ValueError(
                f"EHDB read result missing required fields: {', '.join(missing)}"
            )
        if payload["action"] != "read":
            raise ValueError("EHDB read result action must be 'read'")
        records = payload["records"]
        if not isinstance(records, list) or not all(
            isinstance(record, Mapping) for record in records
        ):
            raise ValueError("EHDB read result records must be a list of objects")
        return cls(
            log_path=_summary_log_path(payload["log_path"]),
            tenant=_result_text(payload["tenant"], "tenant"),
            namespace=_result_text(payload["namespace"], "namespace"),
            stream=_result_text(payload["stream"], "stream"),
            exists=_result_bool(payload["exists"], "exists"),
            record_count=_summary_count(payload["record_count"], "record_count"),
            returned=_summary_count(payload["returned"], "returned"),
            records=tuple(dict(record) for record in records),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": "read",
            "log_path": str(self.log_path),
            "tenant": self.tenant,
            "namespace": self.namespace,
            "stream": self.stream,
            "exists": self.exists,
            "record_count": self.record_count,
            "returned": self.returned,
            "records": [dict(record) for record in self.records],
        }


def _domain_record_invocation(
    adapter: LocalReferenceEhdbAdapter,
    executable: str,
    args: Sequence[str],
) -> LocalReferenceEhdbInvocation:
    """Build an invocation preserving argument values verbatim.

    Unlike :meth:`LocalReferenceEhdbAdapter.helper_invocation`, this does not
    strip arguments — a domain-record payload must reach the helper byte-for-
    byte so the appended record matches what the caller supplied.
    """

    runtime_env = adapter.runtime_env()
    return LocalReferenceEhdbInvocation(
        executable=_non_empty_text(executable, "EHDB helper executable"),
        args=tuple(args),
        env_items=tuple(runtime_env.items()),
        role=adapter.role,
        local_reference_log=adapter.local_reference_log,
    )


def ehdb_local_reference_append_invocation_from_env(
    env: Mapping[str, str] | None = None,
    *,
    stream: str,
    subject: str,
    transaction_id: str,
    payload: str,
    tenant: str | None = None,
    namespace: str | None = None,
) -> LocalReferenceEhdbInvocation | None:
    """Return the concrete ``append`` domain-record helper invocation."""

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
    args = [
        "append",
        "--log",
        str(adapter.local_reference_log),
        "--stream",
        _non_empty_text(stream, "stream"),
        "--subject",
        _non_empty_text(subject, "subject"),
        "--transaction-id",
        _non_empty_text(transaction_id, "transaction_id"),
        "--payload",
        payload,
    ]
    if tenant is not None:
        args.extend(["--tenant", _non_empty_text(tenant, "tenant")])
    if namespace is not None:
        args.extend(["--namespace", _non_empty_text(namespace, "namespace")])
    return _domain_record_invocation(adapter, executable, args)


def ehdb_local_reference_read_invocation_from_env(
    env: Mapping[str, str] | None = None,
    *,
    stream: str,
    after: int | None = None,
    limit: int | None = None,
    tenant: str | None = None,
    namespace: str | None = None,
) -> LocalReferenceEhdbInvocation | None:
    """Return the concrete ``read`` domain-record helper invocation."""

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
    args = [
        "read",
        "--log",
        str(adapter.local_reference_log),
        "--stream",
        _non_empty_text(stream, "stream"),
    ]
    if tenant is not None:
        args.extend(["--tenant", _non_empty_text(tenant, "tenant")])
    if namespace is not None:
        args.extend(["--namespace", _non_empty_text(namespace, "namespace")])
    if limit is not None:
        args.extend(["--limit", str(int(limit))])
    if after is not None:
        args.extend(["--after", str(int(after))])
    return _domain_record_invocation(adapter, executable, args)


def _non_empty_text(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"{label} is required")
    return value.strip()


def _result_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"EHDB result {field} must be a non-empty string")
    return value


def _result_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"EHDB result {field} must be a boolean")
    return value


def _summary_log_path(value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("EHDB summary log_path must be a non-empty string")
    return Path(value)


def _summary_count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"EHDB summary {field} must be an integer")
    if value < 0:
        raise ValueError(f"EHDB summary {field} must be non-negative")
    return value


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
