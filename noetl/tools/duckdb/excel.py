"""Excel export helpers for DuckDB tasks.

This module intercepts DuckDB COPY statements that request XLSX output and
implements them via Polars + XlsxWriter so users can generate Excel workbooks
without relying on DuckDB's optional xlsx extension.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
from collections import OrderedDict
from dataclasses import dataclass
from email.utils import formatdate
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urlparse

import fsspec
import polars as pl

try:  # pragma: no cover - executed at import time
    import xlsxwriter  # type: ignore
except ImportError as exc:  # pragma: no cover - fallback path
    xlsxwriter = None

from noetl.core.logger import setup_logger
from noetl.tools.duckdb.errors import ExcelExportError

logger = setup_logger(__name__, include_location=True)


EXCEL_FORMAT_TOKENS = {"xlsx", "excel"}


@dataclass
class ExcelCopyCommand:
    """Structured representation of a COPY ... FORMAT 'xlsx' statement."""

    query: str
    destination: str
    options: Dict[str, str]
    source_sql: str


@dataclass
class ExcelExportRequest:
    """In-memory record of a pending Excel sheet write."""

    destination: str
    sheet_name: str
    dataframe: pl.DataFrame
    write_mode: str
    source_sql: str
    command_index: int

    @property
    def row_count(self) -> int:
        return int(self.dataframe.height)


@dataclass
class AuthEntry:
    """Normalized representation of a resolved auth item."""

    alias: str
    service: Optional[str]
    payload: Dict[str, Any]
    scope: Optional[str]


class ExcelExportManager:
    """Captures COPY ... FORMAT 'xlsx' commands and writes Excel workbooks."""

    def __init__(self, auth_map: Optional[Dict[str, Any]] = None) -> None:
        self._requests: List[ExcelExportRequest] = []
        self._sheet_counter: int = 0
        self._auth_map: Dict[str, Any] = auth_map or {}

    def try_capture_command(self, connection: Any, sql_command: str, index: int) -> bool:
        """Return True if the SQL command was handled as an Excel export."""

        parsed = parse_excel_copy_command(sql_command)
        if not parsed:
            return False

        logger.info("Routing DuckDB COPY command to Polars Excel writer", extra={
            "destination": parsed.destination,
            "options": parsed.options,
            "command_index": index + 1,
        })

        relation = connection.execute(parsed.query)
        dataframe = relation.pl()

        sheet_name = parsed.options.get("sheet") or self._auto_sheet_name()
        write_mode = (parsed.options.get("write_mode") or "overwrite_sheet").lower()

        if len(sheet_name) > 31:
            raise ExcelExportError(
                f"Worksheet name '{sheet_name}' exceeds Excel limit of 31 characters"
            )

        request = ExcelExportRequest(
            destination=parsed.destination,
            sheet_name=sheet_name,
            dataframe=dataframe,
            write_mode=write_mode,
            source_sql=parsed.source_sql,
            command_index=index + 1,
        )
        self._requests.append(request)
        return True

    def finalize(self) -> List[Dict[str, Any]]:
        """Write any captured Excel exports and return metadata for logging."""

        if not self._requests:
            return []

        grouped: "OrderedDict[str, List[ExcelExportRequest]]" = OrderedDict()
        for request in self._requests:
            grouped.setdefault(request.destination, []).append(request)

        summary: List[Dict[str, Any]] = []
        for destination, sheet_requests in grouped.items():
            summary.append(self._write_workbook(destination, sheet_requests))

        self._requests.clear()
        return summary

    def _auto_sheet_name(self) -> str:
        self._sheet_counter += 1
        return f"Sheet{self._sheet_counter}"

    def _write_workbook(
        self,
        destination: str,
        sheet_requests: List[ExcelExportRequest],
    ) -> Dict[str, Any]:
        logger.debug(
            "Writing Excel workbook",
            extra={"destination": destination, "sheets": [s.sheet_name for s in sheet_requests]},
        )

        if xlsxwriter is None:
            raise ExcelExportError(
                "xlsxwriter dependency is not installed. Install the 'xlsxwriter' package to use COPY ... FORMAT 'xlsx'"
            )

        sheet_names = set()
        for req in sheet_requests:
            if req.sheet_name in sheet_names:
                raise ExcelExportError(
                    f"Duplicate worksheet name '{req.sheet_name}' for destination {destination}"
                )
            sheet_names.add(req.sheet_name)

        buffer = io.BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})

        try:
            for req in sheet_requests:
                req.dataframe.write_excel(workbook=workbook, worksheet=req.sheet_name)
        finally:
            workbook.close()

        data = buffer.getvalue()

        parsed = urlparse(destination)
        if not parsed.scheme:
            local_path = Path(destination).expanduser()
            if local_path.parent and not local_path.parent.exists():
                local_path.parent.mkdir(parents=True, exist_ok=True)

        scheme = (parsed.scheme or "").lower()
        if scheme in {"gs", "gcs"}:
            self._write_to_gcs(destination, data)
        else:
            self._write_with_fsspec(destination, data)

        total_rows = sum(req.row_count for req in sheet_requests)
        return {
            "path": destination,
            "sheets": [req.sheet_name for req in sheet_requests],
            "rows": total_rows,
            "bytes": len(data),
        }

    def _write_with_fsspec(self, destination: str, data: bytes, **storage_options: Any) -> None:
        try:
            with fsspec.open(destination, "wb", **storage_options) as handle:
                handle.write(data)
        except Exception as exc:  # pragma: no cover - fsspec handles many backends
            raise ExcelExportError(
                f"Failed to write Excel workbook to {destination}: {exc}"
            ) from exc

    def _write_to_gcs(self, destination: str, data: bytes) -> None:
        bucket, object_path = _split_cloud_path(destination)
        if not bucket or not object_path:
            raise ExcelExportError(
                f"GCS destination '{destination}' must include bucket and object path"
            )

        auth_entry = self._select_gcs_auth(bucket)
        errors: List[str] = []
        attempted_auth = False

        if auth_entry:
            succeeded, error, attempted = self._try_gcs_service_account(destination, data, auth_entry)
            if attempted:
                attempted_auth = True
                if succeeded:
                    return
                if error:
                    errors.append(f"service account ({auth_entry.alias}): {error}")

            succeeded, error, attempted = self._try_gcs_hmac(bucket, object_path, data, auth_entry)
            if attempted:
                attempted_auth = True
                if succeeded:
                    return
                if error:
                    errors.append(f"hmac ({auth_entry.alias}): {error}")

        if attempted_auth:
            detail = "; ".join(errors) if errors else "no usable authentication mechanism available"
            raise ExcelExportError(
                f"Failed to upload workbook to {destination}. Auth errors: {detail}"
            )

        self._write_with_fsspec(destination, data)

    def _select_gcs_auth(self, bucket: Optional[str]) -> Optional[AuthEntry]:
        for entry in self._iter_auth_entries():
            if not _entry_targets_gcs(entry):
                continue
            if bucket and entry.scope and not _scope_matches_bucket(entry.scope, bucket):
                continue
            return entry
        return None

    def _iter_auth_entries(self) -> Iterable[AuthEntry]:
        for alias, raw in self._auth_map.items():
            if raw is None:
                continue

            payload: Dict[str, Any]
            service: Optional[str]
            scope: Optional[str]

            if hasattr(raw, "payload"):
                payload = getattr(raw, "payload", {}) or {}
                service = getattr(raw, "service", None)
                scope = getattr(raw, "scope", None)
            elif isinstance(raw, dict):
                payload_candidate = raw.get("payload") if isinstance(raw.get("payload"), dict) else raw
                payload = payload_candidate or {}
                service = raw.get("service") or raw.get("type")
                scope = raw.get("scope")
            else:
                continue

            if not isinstance(payload, dict):
                continue

            if service is None:
                service = (
                    payload.get("service")
                    or payload.get("type")
                    or payload.get("provider")
                )

            if scope is None:
                scope = payload.get("scope")

            yield AuthEntry(
                alias=alias,
                service=str(service).lower() if service else None,
                payload=payload,
                scope=scope,
            )

    def _try_gcs_service_account(
        self,
        destination: str,
        data: bytes,
        entry: AuthEntry,
    ) -> Tuple[bool, Optional[str], bool]:
        token = _extract_service_account_token(entry.payload)
        if not token:
            return False, None, False

        storage_options: Dict[str, Any] = {"token": token, "access": "read_write"}
        project = entry.payload.get("project") or entry.payload.get("project_id")
        if project:
            storage_options["project"] = project

        try:
            self._write_with_fsspec(destination, data, **storage_options)
            logger.info(
                "Uploaded Excel workbook to %s using GCS service account alias %s",
                destination,
                entry.alias,
            )
            return True, None, True
        except ExcelExportError as exc:
            logger.warning(
                "Service account upload to %s failed via alias %s: %s",
                destination,
                entry.alias,
                exc,
            )
            return False, str(exc), True

    def _try_gcs_hmac(
        self,
        bucket: str,
        object_path: str,
        data: bytes,
        entry: AuthEntry,
    ) -> Tuple[bool, Optional[str], bool]:
        creds = _extract_hmac_credentials(entry.payload)
        if not creds:
            return False, None, False

        endpoint = creds.get("endpoint") or "https://storage.googleapis.com"

        try:
            _upload_with_gcs_hmac_http(
                key_id=creds["key_id"],
                secret_key=creds["secret_key"],
                endpoint=endpoint,
                bucket=bucket,
                object_path=object_path,
                data=data,
                project_hint=entry.payload.get("project") or entry.payload.get("project_id"),
            )
            logger.info(
                "Uploaded Excel workbook to gs://%s/%s via HMAC alias %s",
                bucket,
                object_path,
                entry.alias,
            )
            return True, None, True
        except ExcelExportError as exc:
            logger.warning(
                "HMAC upload to gs://%s/%s failed via alias %s: %s",
                bucket,
                object_path,
                entry.alias,
                exc,
            )
            return False, str(exc), True


def parse_excel_copy_command(sql: str) -> Optional[ExcelCopyCommand]:
    """Return structured data if the SQL command targets XLSX output."""

    if not sql:
        return None

    text = sql.strip().rstrip(";").strip()
    if not text or not text.upper().startswith("COPY"):
        return None

    lower_text = text.lower()
    if "format" not in lower_text:
        return None

    excel_markers = (
        "format 'xlsx'",
        'format "xlsx"',
        "format 'excel'",
        'format "excel"',
        "format xlsx",
        "format excel",
    )
    if not any(marker in lower_text for marker in excel_markers):
        return None

    try:
        query_sql, remainder = _extract_parenthesized_segment(text)
        destination, options_raw = _parse_destination_and_options(remainder)
        options = _parse_copy_options(options_raw)
    except ExcelExportError:
        raise
    except Exception:
        return None

    format_token = (options.get("format") or "").lower()
    if format_token not in EXCEL_FORMAT_TOKENS:
        return None

    normalized_options = {k.lower(): v for k, v in options.items()}
    return ExcelCopyCommand(
        query=query_sql.strip(),
        destination=destination,
        options=normalized_options,
        source_sql=sql.strip(),
    )


def _extract_parenthesized_segment(sql: str) -> Tuple[str, str]:
    """Extract the SELECT sub-query from COPY ( ... ) ..."""

    start = sql.upper().find("COPY")
    if start == -1:
        raise ExcelExportError("COPY statement missing")

    open_idx = sql.find("(", start)
    if open_idx == -1:
        raise ExcelExportError("COPY statement missing opening parenthesis")

    depth = 0
    in_string = False
    string_char = ""

    for idx in range(open_idx, len(sql)):
        char = sql[idx]
        if in_string:
            if char == string_char:
                in_string = False
            continue

        if char in ("'", '"'):
            in_string = True
            string_char = char
            continue

        if char == "(":
            depth += 1
            continue

        if char == ")":
            depth -= 1
            if depth == 0:
                return sql[open_idx + 1 : idx], sql[idx + 1 :]

    raise ExcelExportError("COPY statement has unbalanced parentheses")


def _parse_destination_and_options(sql: str) -> Tuple[str, Optional[str]]:
    remainder = sql.strip()
    if not remainder:
        raise ExcelExportError("COPY destination missing")

    lower = remainder.lower()
    if not lower.startswith("to"):
        raise ExcelExportError("COPY statement missing TO clause")

    remainder = remainder[2:].strip()
    if not remainder:
        raise ExcelExportError("COPY destination missing path")

    destination, tail = _parse_string_or_token(remainder)
    tail = tail.strip()

    if tail.startswith("("):
        options, rest = _extract_options_block(tail)
        if rest.strip():
            return destination, options
        return destination, options

    return destination, None


def _parse_string_or_token(text: str) -> Tuple[str, str]:
    if text[0] in ("'", '"'):
        quote = text[0]
        end = 1
        while end < len(text):
            if text[end] == quote:
                break
            end += 1
        if end >= len(text):
            raise ExcelExportError("Unterminated string literal in COPY destination")
        return text[1:end], text[end + 1 :]

    # Unquoted token
    parts = text.split(None, 1)
    if not parts:
        raise ExcelExportError("COPY destination path missing")
    destination = parts[0]
    remainder = text[len(destination) :]
    return destination, remainder


def _extract_options_block(text: str) -> Tuple[str, str]:
    depth = 0
    in_string = False
    string_char = ""

    for idx, char in enumerate(text):
        if in_string:
            if char == string_char:
                in_string = False
            continue

        if char in ("'", '"'):
            in_string = True
            string_char = char
            continue

        if char == "(":
            depth += 1
            continue

        if char == ")":
            depth -= 1
            if depth == 0:
                return text[1:idx], text[idx + 1 :]

    raise ExcelExportError("COPY options block is unterminated")


def _parse_copy_options(options_raw: Optional[str]) -> Dict[str, str]:
    if not options_raw:
        return {}

    opts: Dict[str, str] = {}
    current = []
    in_string = False
    string_char = ""

    def _flush() -> None:
        token = "".join(current).strip()
        if not token:
            return
        parts = token.split(None, 1)
        key = parts[0]
        value = parts[1] if len(parts) > 1 else ""
        opts[key.lower()] = _strip_quotes(value.strip())
        current.clear()

    for char in options_raw:
        if in_string:
            if char == string_char:
                in_string = False
            current.append(char)
            continue

        if char in ("'", '"'):
            in_string = True
            string_char = char
            current.append(char)
            continue

        if char == ",":
            _flush()
            continue

        current.append(char)

    _flush()
    return opts


def _strip_quotes(value: str) -> str:
    if not value:
        return value
    if (value.startswith("'") and value.endswith("'")) or (
        value.startswith('"') and value.endswith('"')
    ):
        return value[1:-1]
    return value


def _split_cloud_path(destination: str) -> Tuple[Optional[str], Optional[str]]:
    parsed = urlparse(destination)
    bucket = parsed.netloc or None
    key = parsed.path.lstrip("/") or None
    return bucket, key


def _entry_targets_gcs(entry: AuthEntry) -> bool:
    tokens = {
        entry.service,
        entry.payload.get("service"),
        entry.payload.get("type"),
        entry.payload.get("provider"),
        entry.payload.get("engine"),
    }

    normalized = {str(token).lower() for token in tokens if token}
    return any(token in {"gcs", "gcs_hmac", "hmac"} or token.startswith("gcs") for token in normalized)


def _scope_matches_bucket(scope: str, bucket: str) -> bool:
    if not scope:
        return True
    parsed = urlparse(scope)
    if parsed.scheme in {"gs", "gcs"} and parsed.netloc:
        return parsed.netloc == bucket
    return bucket in scope


def _extract_service_account_token(payload: Dict[str, Any]) -> Optional[Any]:
    candidates = [
        payload.get("service_account_json"),
        payload.get("credentials_json"),
        payload.get("credentials_info"),
        payload.get("token"),
        payload.get("service_account"),
        payload.get("data"),
    ]

    for candidate in candidates:
        token = _coerce_token_candidate(candidate)
        if token:
            return token

    if payload.get("private_key") and payload.get("client_email"):
        return {
            "type": payload.get("type", "service_account"),
            "private_key": payload.get("private_key"),
            "client_email": payload.get("client_email"),
            "client_id": payload.get("client_id"),
            "project_id": payload.get("project_id"),
            "private_key_id": payload.get("private_key_id"),
            "token_uri": payload.get("token_uri", "https://oauth2.googleapis.com/token"),
        }

    return None


def _coerce_token_candidate(candidate: Any) -> Optional[Any]:
    if candidate is None:
        return None
    if isinstance(candidate, dict):
        return candidate
    if isinstance(candidate, str):
        value = candidate.strip()
        if value.startswith("{") and value.endswith("}"):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value or None
    return None


def _extract_hmac_credentials(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    key_id = payload.get("key_id") or payload.get("access_key") or payload.get("access_key_id")
    secret_key = (
        payload.get("secret_key")
        or payload.get("secret")
        or payload.get("secret_access_key")
    )

    if not (key_id and secret_key):
        return None

    return {
        "key_id": key_id,
        "secret_key": secret_key,
        "endpoint": payload.get("endpoint"),
        "region": payload.get("region"),
    }


def _upload_with_gcs_hmac_http(
    *,
    key_id: str,
    secret_key: str,
    endpoint: str,
    bucket: str,
    object_path: str,
    data: bytes,
    project_hint: Optional[str] = None,
) -> None:
    try:
        import requests
    except ImportError as exc:  # pragma: no cover
        raise ExcelExportError("requests is required for GCS HMAC uploads") from exc

    content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    content_md5 = base64.b64encode(hashlib.md5(data).digest()).decode("ascii")
    date_header = formatdate(timeval=None, localtime=False, usegmt=True)
    canonical_resource = f"/{bucket}/{object_path}"
    string_to_sign = "\n".join(["PUT", content_md5, content_type, date_header, canonical_resource])

    digest = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    signature = base64.b64encode(digest).decode("ascii")

    headers = {
        "Content-MD5": content_md5,
        "Content-Type": content_type,
        "Date": date_header,
        "Authorization": f"AWS {key_id}:{signature}",
        "Content-Length": str(len(data)),
    }

    if project_hint:
        headers["x-goog-project-id"] = project_hint

    url = f"{endpoint.rstrip('/')}/{bucket}/{quote(object_path)}"
    response = requests.put(url, headers=headers, data=data)

    if response.status_code >= 300:
        message = response.text.strip() or response.reason
        raise ExcelExportError(
            f"GCS HMAC upload failed: HTTP {response.status_code} {message}"
        )


__all__ = [
    "ExcelExportManager",
    "parse_excel_copy_command",
    "ExcelExportError",
]
