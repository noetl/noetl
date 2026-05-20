#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON_BIN:-.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="${PYTHON_BIN_FALLBACK:-python}"
fi

"$PYTHON_BIN" -m pytest -q \
  tests/core/test_replay_golden_corpus.py \
  tests/core/test_replay_payload_resolver.py \
  tests/scripts/test_fetch_replay_state_report.py \
  tests/scripts/test_run_replay_validation.py \
  tests/scripts/test_export_live_projection_rows_postgres.py \
  tests/scripts/test_check_live_projection_rows.py \
  tests/scripts/test_package_replay_validation_artifacts.py \
  tests/scripts/test_check_replay_validation_bundle.py \
  tests/scripts/test_check_replay_validation_manifest.py \
  tests/scripts/test_check_replay_state_report.py \
  tests/scripts/test_check_replay_parity_report.py \
  tests/scripts/test_check_replay_payload_resolution_report.py \
  tests/scripts/test_fetch_projector_metrics_summary.py \
  tests/scripts/test_check_projector_metrics_summary.py \
  tests/scripts/test_check_projector_phase2_evidence.py \
  tests/api/test_replay_routes.py \
  tests/core/test_replay_upcasters.py \
  tests/core/test_replay_state_projector.py \
  tests/core/test_projector_metrics.py \
  tests/core/test_outbox.py \
  tests/core/test_outbox_publisher_worker.py \
  tests/api/test_command_claim_outbox.py \
  tests/api/test_broker_event_outbox.py \
  tests/unit/dsl/engine/test_executor_outbox.py \
  tests/api/test_frame_routes.py \
  tests/core/test_arrow_ipc_serialization.py \
  tests/core/test_storage_ipc_hint.py \
  tests/core/test_storage_ipc_cache.py
