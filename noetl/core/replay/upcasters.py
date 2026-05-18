"""Schema upcaster registry for replayable event envelopes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

EventUpcaster = Callable[[dict[str, Any]], Mapping[str, Any]]


class EventUpcasterRegistry:
    """Apply versioned event upcasters in a deterministic order."""

    def __init__(self) -> None:
        self._upcasters: dict[tuple[str, int], EventUpcaster] = {}

    def register(self, schema_name: str, from_version: int, upcaster: EventUpcaster) -> None:
        if not schema_name:
            raise ValueError("schema_name is required")
        if from_version < 1:
            raise ValueError("from_version must be >= 1")
        key = (schema_name, from_version)
        if key in self._upcasters:
            raise ValueError(
                f"upcaster already registered for {schema_name} v{from_version}"
            )
        self._upcasters[key] = upcaster

    def upcast_event(self, event: Mapping[str, Any]) -> dict[str, Any]:
        current = dict(event)
        schema_name = str(current.get("schema_name") or "noetl.event")
        version = _schema_version(current.get("schema_version"))

        while True:
            upcaster = self._upcasters.get((schema_name, version))
            if upcaster is None:
                current["schema_name"] = schema_name
                current["schema_version"] = version
                return current
            updated = dict(upcaster(dict(current)))
            next_schema_name = str(updated.get("schema_name") or schema_name)
            next_version = _schema_version(updated.get("schema_version"))
            if next_schema_name == schema_name and next_version <= version:
                raise ValueError(
                    f"upcaster for {schema_name} v{version} did not advance schema_version"
                )
            current = updated
            schema_name = next_schema_name
            version = next_version

    def upcast_events(self, events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        return [self.upcast_event(event) for event in events]

    def digest(self) -> str:
        """Stable digest of registered schema/version transitions."""
        entries = [
            {"schema_name": schema_name, "from_version": from_version}
            for schema_name, from_version in sorted(self._upcasters)
        ]
        payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def _schema_version(value: Any) -> int:
    if value is None:
        return 1
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid schema_version: {value!r}") from exc
    if version < 1:
        raise ValueError("schema_version must be >= 1")
    return version


default_upcaster_registry = EventUpcasterRegistry()
