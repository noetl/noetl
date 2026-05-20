"""Replay API data types shared by services and storage adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class ReplayCutoff:
    """Replay cutoff. Exactly one field is normally set."""

    as_of_event_id: Optional[int] = None
    as_of_position: Optional[int] = None
    as_of_time: Optional[datetime] = None


@dataclass(frozen=True)
class ReplaySnapshotSeed:
    """Snapshot state used as replay seed."""

    aggregate_id: str
    aggregate_type: str
    version: int
    checksum: str
    state: dict[str, Any]
    meta: dict[str, Any]
