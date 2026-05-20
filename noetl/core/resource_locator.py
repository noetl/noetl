"""Utilities for canonical NoETL resource locators.

NoETL locators are durable identities, not transport URLs. They use the
``noetl://`` scheme followed by slash-separated resource segments, for example:

``noetl://tenant/t1/org/o1/cluster/prod/node/node-a/worker/cpu-01``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional
from urllib.parse import quote, unquote, urlparse


SCHEME = "noetl"


class ResourceLocatorError(ValueError):
    """Raised when a NoETL resource locator is malformed."""


@dataclass(frozen=True)
class NoetlResourceLocator:
    """Parsed NoETL resource locator."""

    segments: tuple[str, ...]

    @classmethod
    def parse(cls, value: str) -> "NoetlResourceLocator":
        if not isinstance(value, str) or not value.strip():
            raise ResourceLocatorError("locator must be a non-empty string")
        parsed = urlparse(value.strip())
        if parsed.scheme != SCHEME:
            raise ResourceLocatorError("locator must use noetl:// scheme")
        if parsed.params or parsed.query or parsed.fragment:
            raise ResourceLocatorError("locator must not include params, query, or fragment")

        raw_segments: list[str] = []
        if parsed.netloc:
            raw_segments.append(parsed.netloc)
        raw_segments.extend(part for part in parsed.path.split("/") if part)
        segments = tuple(unquote(part) for part in raw_segments)
        return cls.from_segments(segments)

    @classmethod
    def from_segments(cls, segments: Iterable[str]) -> "NoetlResourceLocator":
        normalized = tuple(_normalize_segment(segment) for segment in segments)
        if not normalized:
            raise ResourceLocatorError("locator must include at least one segment")
        return cls(normalized)

    @classmethod
    def from_pairs(cls, pairs: Mapping[str, object] | Iterable[tuple[str, object]]) -> "NoetlResourceLocator":
        items = pairs.items() if isinstance(pairs, Mapping) else pairs
        segments: list[str] = []
        for key, value in items:
            if value is None or value == "":
                continue
            segments.extend((str(key), str(value)))
        return cls.from_segments(segments)

    @property
    def kind(self) -> str:
        return self.segments[0]

    @property
    def identity(self) -> Optional[str]:
        return self.segments[1] if len(self.segments) > 1 else None

    def value_after(self, key: str) -> Optional[str]:
        """Return the first segment immediately following ``key``."""
        for index, segment in enumerate(self.segments[:-1]):
            if segment == key:
                return self.segments[index + 1]
        return None

    def pairs(self) -> dict[str, str]:
        """Return alternating key/value segments as a dictionary.

        Raises if the locator is not a pure alternating key/value shape.
        """
        if len(self.segments) % 2 != 0:
            raise ResourceLocatorError("locator does not contain alternating key/value segments")
        result: dict[str, str] = {}
        for index in range(0, len(self.segments), 2):
            result[self.segments[index]] = self.segments[index + 1]
        return result

    def child(self, *segments: object) -> "NoetlResourceLocator":
        return NoetlResourceLocator.from_segments((*self.segments, *(str(segment) for segment in segments)))

    def __str__(self) -> str:
        return f"{SCHEME}://" + "/".join(quote(segment, safe="") for segment in self.segments)


def parse_noetl_locator(value: str) -> NoetlResourceLocator:
    return NoetlResourceLocator.parse(value)


def build_noetl_locator(*segments: object) -> str:
    return str(NoetlResourceLocator.from_segments(str(segment) for segment in segments))


def _normalize_segment(segment: object) -> str:
    value = str(segment).strip()
    if not value:
        raise ResourceLocatorError("locator segments must be non-empty")
    if "/" in value:
        raise ResourceLocatorError("locator segments must not contain '/'")
    return value


__all__ = [
    "NoetlResourceLocator",
    "ResourceLocatorError",
    "build_noetl_locator",
    "parse_noetl_locator",
]
