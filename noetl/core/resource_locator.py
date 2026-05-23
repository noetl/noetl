"""Utilities for canonical NoETL resource locators.

NoETL locators are durable identities, not transport URLs. They use the
``noetl://`` scheme followed by slash-separated resource segments, for example:

``noetl://tenant/t1/org/o1/cluster/prod/node/node-a/worker/cpu-01``.

The locator is intentionally minimal and stable: alternating key/value
segments, URL-safe per-segment encoding, no query / fragment / params.
It is the **portable** identity used across the event store
(``payload_ref``), the storage tier (``ResultRef.ref``), the runtime
topology (worker identity), and — starting with Phase 4 — the catalog
and NATS supercluster routing layers.

Beyond the parser, this module exposes:

- :data:`KNOWN_RESOURCE_KINDS` — advisory taxonomy of recognized
  top-level ``kind`` segments. Unknown kinds parse without error;
  the taxonomy is for catalog / router dispatch + warning paths.
- :meth:`NoetlResourceLocator.to_nats_subject` /
  :meth:`NoetlResourceLocator.from_nats_subject` — canonical
  derivation of a NATS-safe subject from a locator. Phase 4
  round 3 (NATS supercluster) leans on this.
- :meth:`NoetlResourceLocator.locality` — extract the locality
  segments (``region`` / ``zone`` / ``cluster`` / ``node``) into a
  plain dict, without callers having to know the schema.
- :func:`dataset_locator` / :func:`stream_locator` /
  :func:`partition_locator` — data-resource URN builders for the
  future catalog routing work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional
from urllib.parse import quote, unquote, urlparse


SCHEME = "noetl"

#: NATS subject root for every NoETL-derived subject. All subjects
#: produced by :meth:`NoetlResourceLocator.to_nats_subject` start
#: with this prefix so NATS subject-permission rules can match
#: ``noetl.>``.
NATS_SUBJECT_ROOT = "noetl"

#: Regex matching characters that are NOT allowed in a NATS subject
#: segment. NATS accepts ``[a-zA-Z0-9_-]`` plus the wildcards ``*``
#: and ``>``; concrete subjects (what the locator emits) keep only
#: the alphanumerics + ``_`` and ``-``.
_NATS_SAFE_RE = re.compile(r"[^a-zA-Z0-9_-]")

#: Advisory taxonomy of recognized top-level locator ``kind``
#: segments. The set is intentionally extensible: parsing an
#: unknown kind does not raise. Catalog / router code should check
#: :attr:`NoetlResourceLocator.is_known_kind` and decide its own
#: policy (log, warn, route to a default, etc.).
KNOWN_RESOURCE_KINDS = frozenset(
    {
        "tenant",  # worker / runtime identity
        "execution",  # playbook execution
        "dataset",  # logical dataset for catalog routing
        "stream",  # event / data stream
        "partition",  # physical partition of a stream
        "payload",  # content-addressed payload (pairs with payload_store URIs)
    }
)

#: Locality segments recognized by :meth:`NoetlResourceLocator.locality`,
#: in coarse-to-fine order. Builders emit them in this order so URN
#: prefixes sort naturally by geographic scope.
LOCALITY_KEYS = ("region", "zone", "cluster", "node")


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

    @classmethod
    def from_nats_subject(cls, subject: str) -> "NoetlResourceLocator":
        """Parse a NATS subject produced by :meth:`to_nats_subject`.

        Strips the :data:`NATS_SUBJECT_ROOT` prefix, splits on ``.``,
        and rebuilds the locator from the resulting segments. Because
        :meth:`to_nats_subject` is **lossy** (URL-quoted bytes collapse
        to ``_``), round-trip is only guaranteed when every original
        segment is already NATS-safe.
        """
        if not isinstance(subject, str) or not subject.strip():
            raise ResourceLocatorError("nats subject must be a non-empty string")
        cleaned = subject.strip()
        prefix = f"{NATS_SUBJECT_ROOT}."
        if not cleaned.startswith(prefix):
            raise ResourceLocatorError(
                f"nats subject must start with {prefix!r}: {subject!r}"
            )
        body = cleaned[len(prefix) :]
        if not body:
            raise ResourceLocatorError("nats subject has no segments after the root prefix")
        return cls.from_segments(body.split("."))

    @property
    def kind(self) -> str:
        return self.segments[0]

    @property
    def identity(self) -> Optional[str]:
        return self.segments[1] if len(self.segments) > 1 else None

    @property
    def is_known_kind(self) -> bool:
        """``True`` iff :attr:`kind` is in :data:`KNOWN_RESOURCE_KINDS`.

        Advisory only — the parser never rejects unknown kinds.
        Catalog / router code should branch on this and decide its
        own policy.
        """
        return self.kind in KNOWN_RESOURCE_KINDS

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

    def locality(self) -> dict[str, str]:
        """Return locality segments (``region``/``zone``/``cluster``/``node``).

        Returns an empty dict when no locality segments are present.
        The returned dict's keys preserve the coarse-to-fine order
        from :data:`LOCALITY_KEYS`.
        """
        result: dict[str, str] = {}
        for key in LOCALITY_KEYS:
            value = self.value_after(key)
            if value:
                result[key] = value
        return result

    def to_nats_subject(self) -> str:
        """Derive a canonical NATS-safe subject from the locator.

        Mapping rules:

        - Strip the ``noetl://`` scheme.
        - For each segment: keep ``[a-zA-Z0-9_-]`` characters; replace
          any other byte with ``_``. URL-quoted segments (e.g.
          ``r%26d``) thus collapse to underscores; the mapping is
          **lossy** for non-NATS-safe segments.
        - Prefix with :data:`NATS_SUBJECT_ROOT` (``noetl``) so NATS
          subject-permission rules can match ``noetl.>``.
        - Join with ``.`` (the NATS segment separator).

        Example::

            >>> NoetlResourceLocator.from_segments(
            ...     ["tenant", "acme", "org", "research", "cluster", "us-east-1"]
            ... ).to_nats_subject()
            'noetl.tenant.acme.org.research.cluster.us-east-1'
        """
        safe_segments = [_NATS_SAFE_RE.sub("_", segment) for segment in self.segments]
        return ".".join((NATS_SUBJECT_ROOT, *safe_segments))

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


def _locality_pairs(
    *,
    region: Optional[str],
    zone: Optional[str],
    cluster_id: Optional[str],
    node_id: Optional[str] = None,
) -> list[tuple[str, str]]:
    """Build alternating-pair tuples for the locality segments that are set."""
    pairs: list[tuple[str, str]] = []
    if region:
        pairs.append(("region", str(region)))
    if zone:
        pairs.append(("zone", str(zone)))
    if cluster_id:
        pairs.append(("cluster", str(cluster_id)))
    if node_id:
        pairs.append(("node", str(node_id)))
    return pairs


def dataset_locator(
    tenant_id: str,
    organization_id: str,
    dataset_id: str,
    *,
    region: Optional[str] = None,
    zone: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> str:
    """Build a canonical dataset URN.

    Shape::

        noetl://tenant/<t>/org/<o>[/region/<r>][/zone/<z>][/cluster/<c>]/dataset/<id>

    Locality segments are included only when their argument is set.
    """
    pairs: list[tuple[str, str]] = [
        ("tenant", str(tenant_id)),
        ("org", str(organization_id)),
    ]
    pairs.extend(_locality_pairs(region=region, zone=zone, cluster_id=cluster_id))
    pairs.append(("dataset", str(dataset_id)))
    return str(NoetlResourceLocator.from_pairs(pairs))


def stream_locator(
    tenant_id: str,
    organization_id: str,
    stream_id: str,
    *,
    region: Optional[str] = None,
    zone: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> str:
    """Build a canonical stream URN.

    Shape::

        noetl://tenant/<t>/org/<o>[/region/<r>][/zone/<z>][/cluster/<c>]/stream/<id>
    """
    pairs: list[tuple[str, str]] = [
        ("tenant", str(tenant_id)),
        ("org", str(organization_id)),
    ]
    pairs.extend(_locality_pairs(region=region, zone=zone, cluster_id=cluster_id))
    pairs.append(("stream", str(stream_id)))
    return str(NoetlResourceLocator.from_pairs(pairs))


def partition_locator(
    tenant_id: str,
    organization_id: str,
    stream_id: str,
    partition_index: int | str,
    *,
    region: Optional[str] = None,
    zone: Optional[str] = None,
    cluster_id: Optional[str] = None,
) -> str:
    """Build a canonical partition URN.

    Shape::

        noetl://tenant/<t>/org/<o>[/region/<r>][/zone/<z>][/cluster/<c>]/stream/<sid>/partition/<idx>
    """
    pairs: list[tuple[str, str]] = [
        ("tenant", str(tenant_id)),
        ("org", str(organization_id)),
    ]
    pairs.extend(_locality_pairs(region=region, zone=zone, cluster_id=cluster_id))
    pairs.append(("stream", str(stream_id)))
    pairs.append(("partition", str(partition_index)))
    return str(NoetlResourceLocator.from_pairs(pairs))


__all__ = [
    "KNOWN_RESOURCE_KINDS",
    "LOCALITY_KEYS",
    "NATS_SUBJECT_ROOT",
    "NoetlResourceLocator",
    "ResourceLocatorError",
    "build_noetl_locator",
    "dataset_locator",
    "parse_noetl_locator",
    "partition_locator",
    "stream_locator",
]
