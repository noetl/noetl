"""Tests for the EventEmitRequest validation aliases introduced
in R-1.2 PR-EE-4 (cross-repo event envelope reconciliation).

Locks in three back-compat guarantees:

1. Producers sending the executor's `ExecutorEvent` shape
   (canonical names: `event_type`, `node_name`, `context`) round-
   trip cleanly.
2. Producers sending the worker's pre-EE `WorkerEvent` shape
   (legacy names: `name`, `step`, `payload`) deserialize via the
   `validation_alias=AliasChoices(...)` declarations.
3. The new `worker_id` field is accepted as a top-level field.

See `agents/rules/observability.md` Principle 3 for the
`event_id` snowflake contract that this schema accepts but does
not require.
"""

from __future__ import annotations

import pytest

from noetl.server.api.broker.schema import EventEmitRequest


def _minimum_required() -> dict:
    return {
        "execution_id": "478775660589088776",
        "event_type": "step.enter",
    }


class TestEventTypeAlias:
    """`event_type` is the canonical name; `name` is the alias."""

    def test_canonical_event_type_works(self):
        req = EventEmitRequest.model_validate(_minimum_required())
        assert req.event_type == "step.enter"

    def test_legacy_name_alias_deserializes_into_event_type(self):
        # Pre-PR-EE clients (worker before EE-3) might send `name`.
        body = {"execution_id": "1", "name": "step.exit"}
        req = EventEmitRequest.model_validate(body)
        assert req.event_type == "step.exit"


class TestNodeNameAlias:
    """`node_name` is the canonical name; `step` is the alias."""

    def test_canonical_node_name_works(self):
        req = EventEmitRequest.model_validate(
            {**_minimum_required(), "node_name": "fetch"}
        )
        assert req.node_name == "fetch"

    def test_step_alias_deserializes_into_node_name(self):
        # Executor's `ExecutorEvent.step` field should land in
        # `node_name` on the server side.
        req = EventEmitRequest.model_validate(
            {**_minimum_required(), "step": "fetch_calendar"}
        )
        assert req.node_name == "fetch_calendar"


class TestContextAlias:
    """`context` is the canonical name; `payload` is the alias."""

    def test_canonical_context_works(self):
        req = EventEmitRequest.model_validate(
            {**_minimum_required(), "context": {"foo": "bar"}}
        )
        assert req.context == {"foo": "bar"}

    def test_payload_alias_deserializes_into_context(self):
        # Worker's pre-EE `WorkerEvent.payload` should land in
        # `context` on the server side.
        req = EventEmitRequest.model_validate(
            {**_minimum_required(), "payload": {"items": 42}}
        )
        assert req.context == {"items": 42}


class TestWorkerId:
    """`worker_id` is a new explicit top-level field (R-1.2 PR-EE-4)."""

    def test_worker_id_accepted_as_top_level_field(self):
        req = EventEmitRequest.model_validate(
            {**_minimum_required(), "worker_id": "worker-prod-7"}
        )
        assert req.worker_id == "worker-prod-7"

    def test_worker_id_defaults_to_none_when_omitted(self):
        req = EventEmitRequest.model_validate(_minimum_required())
        assert req.worker_id is None

    def test_worker_id_omitted_from_serialized_when_none(self):
        req = EventEmitRequest.model_validate(_minimum_required())
        dumped = req.model_dump(exclude_none=True)
        assert "worker_id" not in dumped


class TestFullExecutorEnvelopeRoundTrips:
    """The full ExecutorEvent shape (per noetl-executor 0.3.1)
    deserializes cleanly via the aliases."""

    def test_executor_shape_round_trip(self):
        # This is the wire shape noetl-executor 0.3.1 produces
        # AND the noetl-server (Rust, post-EE-2) accepts.  Python
        # should also accept it now.
        wire = {
            "execution_id": "478775660589088776",
            "event_type": "command.completed",
            "step": "fetch_calendar",
            "status": "COMPLETED",
            "created_at": "2026-05-31T03:14:15Z",
            "context": {"items": 42},
            "event_id": "478775660589088777",
            "worker_id": "worker-prod-7",
            "meta": {"attempts": 2},
        }
        req = EventEmitRequest.model_validate(wire)
        assert req.execution_id == "478775660589088776"
        assert req.event_type == "command.completed"
        assert req.node_name == "fetch_calendar"
        assert req.status == "COMPLETED"
        assert req.event_id == "478775660589088777"
        assert req.worker_id == "worker-prod-7"
        assert req.meta == {"attempts": 2}
        assert req.context == {"items": 42}


class TestLegacyWorkerShape:
    """Pre-EE worker wire format (everything in payload, name not
    event_type) deserializes via the aliases."""

    def test_legacy_worker_shape(self):
        # This is what the worker sends today (pre-EE-3).  Server
        # should accept it without any changes on the worker side.
        wire = {
            "execution_id": "478775660589088776",
            "name": "call.done",  # legacy field name
            "step": "fetch",  # legacy field name
            "payload": {"result": "ok"},  # legacy field name
        }
        req = EventEmitRequest.model_validate(wire)
        assert req.event_type == "call.done"
        assert req.node_name == "fetch"
        assert req.context == {"result": "ok"}
