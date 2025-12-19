from dataclasses import dataclass
from typing import Dict


@dataclass
class StepSpec:
    id: str
    type: str
    resources: Dict[str, int]
    duration_ms: int
    tags: Dict[str, str]


@dataclass
class Edge:
    u: str  # predecessor
    v: str  # successor


@dataclass
class ResourceCap:
    name: str
    capacity: int


@dataclass
class Schedule:
    starts_ms: Dict[str, int]
    ends_ms: Dict[str, int]
    durations_ms: Dict[str, int]
