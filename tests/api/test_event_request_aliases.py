"""Tests for the EventRequest validation aliases added in the
EE-4 broker-endpoint completion (2026-05-31).

The legacy ``EventRequest`` model in ``noetl.server.api.core.models``
backs the mounted ``/api/events`` endpoint.  Pre-fix it only accepted
the legacy field shape (``name``, ``payload``, ``execution_id: str``);
the EE-4 ``EventEmitRequest`` schema with aliases lived in
``broker/endpoint.py`` but was dead code (never mounted).

This change makes the actual mounted endpoint honor the EE-3 / EE-4
wire shape (the Rust noetl-worker now sends ``event_type`` /
``context`` / ``execution_id: int|str``).  These tests lock that in.

See ``tests/api/test_event_emit_request_aliases.py`` for the
companion tests on the dead-code broker schema.
"""

from __future__ import annotations

from noetl.server.api.core.models import EventRequest


def _minimum_required() -> dict:
    """Just the truly required fields, in the canonical (EE-4) shape."""
    return {
        "execution_id": "478775660589088776",
        "event_type": "step.enter",
        "step": "fetch_calendar",
    }


class TestEventTypeAlias:
    """``name`` is the canonical EventRequest field; ``event_type`` is
    accepted as an alias so EE-3 workers don't need to translate."""

    def test_canonical_name_works(self):
        req = EventRequest.model_validate({**_minimum_required(), "name": "step.enter"})
        assert req.name == "step.enter"

    def test_event_type_alias_deserializes_into_name(self):
        # EE-3 / EE-4 producers send `event_type`.
        req = EventRequest.model_validate(_minimum_required())
        assert req.name == "step.enter"


class TestStepAlias:
    """``step`` is the canonical EventRequest field; ``node_name`` is
    accepted as an alias.  Matches the Python broker's
    ``EventEmitRequest`` shape (where ``node_name`` is canonical)."""

    def test_canonical_step_works(self):
        body = {**_minimum_required(), "step": "fetch"}
        req = EventRequest.model_validate(body)
        assert req.step == "fetch"

    def test_node_name_alias_deserializes_into_step(self):
        body = {**_minimum_required(), "node_name": "fetch_calendar_alt"}
        body.pop("step")
        req = EventRequest.model_validate(body)
        assert req.step == "fetch_calendar_alt"


class TestPayloadContextAlias:
    """``payload`` is the canonical EventRequest field; ``context`` is
    accepted as an alias (EE-3 Rust worker emits ``context``)."""

    def test_canonical_payload_works(self):
        req = EventRequest.model_validate(
            {**_minimum_required(), "payload": {"items": 1}}
        )
        assert req.payload == {"items": 1}

    def test_context_alias_deserializes_into_payload(self):
        req = EventRequest.model_validate(
            {**_minimum_required(), "context": {"items": 42}}
        )
        assert req.payload == {"items": 42}


class TestExecutionIdCoercion:
    """``execution_id`` accepts JSON string OR integer on the wire and
    stringifies before storage so the rest of the engine keeps its
    ``str`` invariant."""

    def test_string_passthrough(self):
        req = EventRequest.model_validate(
            {**_minimum_required(), "execution_id": "12345"}
        )
        assert req.execution_id == "12345"

    def test_integer_coerced_to_string(self):
        # The Rust noetl-worker's `ExecutorEvent.execution_id: i64`
        # serialises to a JSON number.  Pre-fix the engine rejected
        # it with `Input should be a valid string`.
        body = _minimum_required()
        body["execution_id"] = 638758527854445253
        req = EventRequest.model_validate(body)
        assert req.execution_id == "638758527854445253"


class TestFullExecutorEnvelopeRoundTrips:
    """The complete EE-3 wire shape (per noetl-executor 0.3.1 +
    noetl-worker 3.0.0+) deserializes cleanly via the aliases AND
    integer coercion."""

    def test_executor_envelope(self):
        wire = {
            "execution_id": 478775660589088776,
            "event_type": "command.completed",
            "step": "fetch_calendar",
            "status": "COMPLETED",
            "created_at": "2026-05-31T03:14:15Z",
            "context": {"items": 42},
            "event_id": "478775660589088777",
            "worker_id": "noetl-worker-rust-prod-7",
            "meta": {"attempts": 2},
        }
        req = EventRequest.model_validate(wire)
        assert req.execution_id == "478775660589088776"
        assert req.name == "command.completed"
        assert req.step == "fetch_calendar"
        assert req.payload == {"items": 42}
        assert req.meta == {"attempts": 2}
        assert req.worker_id == "noetl-worker-rust-prod-7"
        # `event_id`, `status`, `created_at` aren't fields on
        # EventRequest — they're silently dropped (Pydantic's
        # default behaviour for extra fields).  The handler does
        # not consume them today; if/when it needs them, add the
        # fields to the model.


class TestLegacyShape:
    """The pre-EE wire format (what the Python noetl-worker has been
    sending for years) keeps working bit-for-bit."""

    def test_legacy_worker_payload(self):
        wire = {
            "execution_id": "478775660589088776",
            "name": "call.done",
            "step": "fetch",
            "payload": {"result": "ok"},
            "worker_id": "noetl-worker-py-1",
        }
        req = EventRequest.model_validate(wire)
        assert req.execution_id == "478775660589088776"
        assert req.name == "call.done"
        assert req.step == "fetch"
        assert req.payload == {"result": "ok"}
        assert req.worker_id == "noetl-worker-py-1"
