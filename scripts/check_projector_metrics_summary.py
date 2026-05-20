#!/usr/bin/env python
"""Validate projector metrics summary JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REQUIRED_ACTION_FIELDS = (
    "actions_total",
    "acknowledged_notifications_total",
    "redelivery_requests_total",
    "delayed_redelivery_requests_total",
    "terminated_notifications_total",
    "ack_ratio",
    "redelivery_ratio",
    "termination_ratio",
)

REQUIRED_BATCH_FIELDS = (
    "extracted_events",
    "owned_events",
    "unowned_events",
    "unshardable_events",
    "projection_records",
    "stale_projection_records",
    "owned_ratio",
    "unowned_ratio",
    "unshardable_ratio",
    "projection_record_ratio",
    "stale_projection_ratio",
)

REQUIRED_ERROR_FIELDS = (
    "errors_total",
    "decode_errors_total",
    "projection_errors_total",
    "decode_error_ratio",
    "projection_error_ratio",
    "last_error_unixtime",
)

REQUIRED_SUMMARY_FIELDS = (
    "notifications_total",
    "last_success_unixtime",
    "last_error_unixtime",
    "last_projection_source_event_id",
    "last_projection_event_time_watermark_unixtime",
    "last_projection_projected_at_unixtime",
    "last_projection_lag_milliseconds",
    "max_projection_lag_milliseconds",
    "actions",
    "batch",
    "errors",
)


def _load_report(path: Path) -> dict[str, Any]:
    data: Any = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _validate_number(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
    minimum: float | None = 0.0,
) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        failures.append({"field": field, "reason": "must be a number", "supplied": value})
        return None
    parsed = float(value)
    if minimum is not None and parsed < minimum:
        failures.append({"field": field, "reason": f"must be >= {minimum}", "supplied": value})
    return parsed


def _validate_ratio(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
) -> float | None:
    parsed = _validate_number(failures, field=field, value=value, minimum=0.0)
    if parsed is not None and parsed > 1.0:
        failures.append({"field": field, "reason": "must be <= 1.0", "supplied": value})
    return parsed


def _validate_object(
    failures: list[dict[str, Any]],
    *,
    field: str,
    value: Any,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        failures.append({"field": field, "reason": "must be an object", "supplied": value})
        return None
    return value


def _validate_required_fields(
    failures: list[dict[str, Any]],
    *,
    prefix: str,
    value: Mapping[str, Any],
    fields: tuple[str, ...],
) -> None:
    for field in fields:
        if field not in value:
            failures.append({"field": f"{prefix}.{field}", "reason": "missing required field"})


def _validate_labels(failures: list[dict[str, Any]], labels: Any) -> None:
    labels_obj = _validate_object(failures, field="labels", value=labels)
    if labels_obj is None:
        return
    for key, value in labels_obj.items():
        if not isinstance(key, str) or not key:
            failures.append({"field": "labels", "reason": "label keys must be non-empty strings"})
        if not isinstance(value, str) or not value:
            failures.append(
                {
                    "field": f"labels.{key}",
                    "reason": "label values must be non-empty strings",
                    "supplied": value,
                }
            )


def _validate_action_summary(failures: list[dict[str, Any]], actions: Mapping[str, Any]) -> None:
    _validate_required_fields(failures, prefix="summary.actions", value=actions, fields=REQUIRED_ACTION_FIELDS)
    for field in REQUIRED_ACTION_FIELDS:
        if field.endswith("_ratio"):
            _validate_ratio(failures, field=f"summary.actions.{field}", value=actions.get(field))
        else:
            _validate_number(failures, field=f"summary.actions.{field}", value=actions.get(field))


def _validate_batch_summary(failures: list[dict[str, Any]], batch: Mapping[str, Any]) -> None:
    _validate_required_fields(failures, prefix="summary.batch", value=batch, fields=REQUIRED_BATCH_FIELDS)
    for field in REQUIRED_BATCH_FIELDS:
        if field.endswith("_ratio"):
            _validate_ratio(failures, field=f"summary.batch.{field}", value=batch.get(field))
        else:
            _validate_number(failures, field=f"summary.batch.{field}", value=batch.get(field))


def _validate_error_summary(failures: list[dict[str, Any]], errors: Mapping[str, Any]) -> None:
    _validate_required_fields(failures, prefix="summary.errors", value=errors, fields=REQUIRED_ERROR_FIELDS)
    for field in REQUIRED_ERROR_FIELDS:
        if field.endswith("_ratio"):
            _validate_ratio(failures, field=f"summary.errors.{field}", value=errors.get(field))
        else:
            _validate_number(failures, field=f"summary.errors.{field}", value=errors.get(field))


def validate_projector_metrics_summary(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    _validate_labels(failures, report.get("labels"))

    summary = _validate_object(failures, field="summary", value=report.get("summary"))
    if summary is None:
        return {"matched": False, "failures": failures}

    _validate_required_fields(failures, prefix="summary", value=summary, fields=REQUIRED_SUMMARY_FIELDS)
    for field in REQUIRED_SUMMARY_FIELDS:
        if field in {"actions", "batch", "errors"}:
            continue
        _validate_number(failures, field=f"summary.{field}", value=summary.get(field))

    actions = _validate_object(failures, field="summary.actions", value=summary.get("actions"))
    if actions is not None:
        _validate_action_summary(failures, actions)

    batch = _validate_object(failures, field="summary.batch", value=summary.get("batch"))
    if batch is not None:
        _validate_batch_summary(failures, batch)

    errors = _validate_object(failures, field="summary.errors", value=summary.get("errors"))
    if errors is not None:
        _validate_error_summary(failures, errors)

    return {"matched": not failures, "failures": failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate NoETL projector /summary JSON",
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Projector metrics summary JSON returned by /summary",
    )
    args = parser.parse_args(argv)

    output = validate_projector_metrics_summary(_load_report(args.report))
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0 if output["matched"] else 1


if __name__ == "__main__":
    sys.exit(main())
