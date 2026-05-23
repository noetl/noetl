from __future__ import annotations

import pytest


def test_resource_locator_parses_execution_result_ref():
    from noetl.core.resource_locator import parse_noetl_locator

    locator = parse_noetl_locator("noetl://execution/123/result/load/abcd")

    assert locator.kind == "execution"
    assert locator.identity == "123"
    assert locator.value_after("result") == "load"
    assert str(locator) == "noetl://execution/123/result/load/abcd"


def test_resource_locator_builds_cloud_os_identity():
    from noetl.core.resource_locator import NoetlResourceLocator

    locator = NoetlResourceLocator.from_pairs(
        [
            ("tenant", "tenant-123"),
            ("org", "org-456"),
            ("cluster", "prod-1"),
            ("node", "node-a"),
            ("worker", "cpu-01"),
        ]
    )

    assert str(locator) == "noetl://tenant/tenant-123/org/org-456/cluster/prod-1/node/node-a/worker/cpu-01"
    assert locator.pairs()["worker"] == "cpu-01"


def test_resource_locator_quotes_and_decodes_segments():
    from noetl.core.resource_locator import build_noetl_locator, parse_noetl_locator

    encoded = build_noetl_locator("tenant", "tenant 123", "org", "r&d")
    locator = parse_noetl_locator(encoded)

    assert encoded == "noetl://tenant/tenant%20123/org/r%26d"
    assert locator.value_after("tenant") == "tenant 123"
    assert locator.value_after("org") == "r&d"


def test_resource_locator_rejects_non_noetl_urls():
    from noetl.core.resource_locator import ResourceLocatorError, parse_noetl_locator

    with pytest.raises(ResourceLocatorError, match="noetl://"):
        parse_noetl_locator("https://example.com")


def test_resource_locator_rejects_query_and_slash_segments():
    from noetl.core.resource_locator import NoetlResourceLocator, ResourceLocatorError, parse_noetl_locator

    with pytest.raises(ResourceLocatorError, match="query"):
        parse_noetl_locator("noetl://execution/123?debug=true")

    with pytest.raises(ResourceLocatorError, match="must not contain"):
        NoetlResourceLocator.from_segments(["execution", "bad/id"])


# ---------------------------------------------------------------------------
# Phase 4 round 1 — URN extension
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["tenant", "execution", "dataset", "stream", "partition", "payload"])
def test_known_kind_taxonomy_recognizes_each_kind(kind: str):
    from noetl.core.resource_locator import NoetlResourceLocator

    locator = NoetlResourceLocator.from_segments([kind, "some-id"])
    assert locator.is_known_kind is True


def test_known_kind_taxonomy_reports_unknown_without_error():
    """Unknown kinds parse cleanly; is_known_kind reports False without raising."""
    from noetl.core.resource_locator import NoetlResourceLocator

    locator = NoetlResourceLocator.from_segments(["spaceship", "enterprise-d"])
    assert locator.is_known_kind is False
    # The locator itself remains usable
    assert str(locator) == "noetl://spaceship/enterprise-d"
    assert locator.kind == "spaceship"


def test_known_kind_taxonomy_exports_expected_set():
    from noetl.core.resource_locator import KNOWN_RESOURCE_KINDS

    assert KNOWN_RESOURCE_KINDS == frozenset(
        {"tenant", "execution", "dataset", "stream", "partition", "payload"}
    )


@pytest.mark.parametrize(
    "segments",
    [
        ["tenant", "acme", "org", "research", "cluster", "us-east-1", "worker", "cpu-01"],
        ["execution", "12345"],
        ["payload", "sha256-abc"],
        ["tenant", "acme", "org", "research", "stream", "orders-v1", "partition", "7"],
    ],
)
def test_to_nats_subject_round_trip_for_nats_safe_segments(segments):
    from noetl.core.resource_locator import NoetlResourceLocator

    locator = NoetlResourceLocator.from_segments(segments)
    subject = locator.to_nats_subject()
    round_tripped = NoetlResourceLocator.from_nats_subject(subject)

    # Round-trip identity for NATS-safe segments
    assert tuple(round_tripped.segments) == tuple(segments)
    # And the string form survives
    assert str(round_tripped) == str(locator)


def test_to_nats_subject_collapses_unsafe_chars():
    """Non-NATS-safe characters in a segment collapse to underscores. Lossy."""
    from noetl.core.resource_locator import NoetlResourceLocator

    locator = NoetlResourceLocator.from_segments(["tenant", "r&d", "org", "team alpha"])
    subject = locator.to_nats_subject()
    assert subject == "noetl.tenant.r_d.org.team_alpha"

    # Round-trip is lossy when the original was unsafe — what we get back
    # is the collapsed form, not the original.
    round_tripped = NoetlResourceLocator.from_nats_subject(subject)
    assert tuple(round_tripped.segments) == ("tenant", "r_d", "org", "team_alpha")


def test_to_nats_subject_prefix_is_noetl():
    from noetl.core.resource_locator import NoetlResourceLocator

    locator = NoetlResourceLocator.from_segments(["execution", "abc"])
    subject = locator.to_nats_subject()
    assert subject.startswith("noetl.")


def test_to_nats_subject_does_not_emit_nats_forbidden_chars():
    """The subject string only contains NATS-safe chars plus '.'.

    Segments are limited to ``[a-zA-Z0-9_-]`` by the lossy mapping
    (``/`` is impossible to land in a segment because the parser
    rejects it before we ever reach ``to_nats_subject``).
    """
    import re

    from noetl.core.resource_locator import NoetlResourceLocator

    locator = NoetlResourceLocator.from_segments(
        ["tenant", "ten?ant", "org", "team alpha", "cluster", "us east", "wild", "ca*re>t"]
    )
    subject = locator.to_nats_subject()
    # Segments must be [a-zA-Z0-9_-], joined by '.'
    assert re.fullmatch(r"[a-zA-Z0-9_.-]+", subject)
    # And explicitly: no NATS-wildcard or query-style chars survived
    for forbidden in ("?", "*", ">", " "):
        assert forbidden not in subject


def test_from_nats_subject_rejects_missing_prefix():
    from noetl.core.resource_locator import NoetlResourceLocator, ResourceLocatorError

    with pytest.raises(ResourceLocatorError, match="must start with 'noetl."):
        NoetlResourceLocator.from_nats_subject("foo.bar.baz")


def test_from_nats_subject_rejects_empty_body():
    from noetl.core.resource_locator import NoetlResourceLocator, ResourceLocatorError

    with pytest.raises(ResourceLocatorError, match="no segments after the root prefix"):
        NoetlResourceLocator.from_nats_subject("noetl.")


def test_from_nats_subject_rejects_empty_input():
    from noetl.core.resource_locator import NoetlResourceLocator, ResourceLocatorError

    with pytest.raises(ResourceLocatorError, match="non-empty string"):
        NoetlResourceLocator.from_nats_subject("")


def test_locality_extracts_present_segments():
    from noetl.core.resource_locator import parse_noetl_locator

    locator = parse_noetl_locator(
        "noetl://tenant/acme/org/research/region/us-east1/zone/us-east1-b"
        "/cluster/prod/node/node-a/worker/cpu-01"
    )

    assert locator.locality() == {
        "region": "us-east1",
        "zone": "us-east1-b",
        "cluster": "prod",
        "node": "node-a",
    }


def test_locality_returns_empty_for_no_locality_segments():
    from noetl.core.resource_locator import parse_noetl_locator

    locator = parse_noetl_locator("noetl://execution/123/result/load/abc")
    assert locator.locality() == {}


def test_locality_returns_only_set_segments():
    from noetl.core.resource_locator import parse_noetl_locator

    locator = parse_noetl_locator("noetl://tenant/acme/org/research/region/us-east1/dataset/x")
    assert locator.locality() == {"region": "us-east1"}


def test_dataset_locator_builds_canonical_shape():
    from noetl.core.resource_locator import dataset_locator

    # Without locality
    assert (
        dataset_locator("acme", "research", "sales-2026")
        == "noetl://tenant/acme/org/research/dataset/sales-2026"
    )

    # With full locality
    assert (
        dataset_locator(
            "acme",
            "research",
            "sales-2026",
            region="us-east1",
            zone="us-east1-b",
            cluster_id="prod",
        )
        == "noetl://tenant/acme/org/research/region/us-east1/zone/us-east1-b"
        "/cluster/prod/dataset/sales-2026"
    )


def test_dataset_locator_skips_unset_locality_fields():
    from noetl.core.resource_locator import dataset_locator

    # Only region set — zone / cluster omitted
    assert (
        dataset_locator("acme", "research", "ds-1", region="us-east1")
        == "noetl://tenant/acme/org/research/region/us-east1/dataset/ds-1"
    )


def test_stream_locator_builds_canonical_shape():
    from noetl.core.resource_locator import stream_locator

    assert (
        stream_locator("acme", "research", "orders-v1")
        == "noetl://tenant/acme/org/research/stream/orders-v1"
    )

    assert (
        stream_locator("acme", "research", "orders-v1", cluster_id="prod-1")
        == "noetl://tenant/acme/org/research/cluster/prod-1/stream/orders-v1"
    )


def test_partition_locator_includes_stream_id_and_index():
    from noetl.core.resource_locator import partition_locator

    assert (
        partition_locator("acme", "research", "orders-v1", 7)
        == "noetl://tenant/acme/org/research/stream/orders-v1/partition/7"
    )

    # Integer index renders as string
    assert (
        partition_locator("acme", "research", "orders-v1", 0, region="us-east1")
        == "noetl://tenant/acme/org/research/region/us-east1/stream/orders-v1/partition/0"
    )


def test_data_resource_locators_round_trip_through_parser():
    """The data-resource builders produce URNs that the parser accepts."""
    from noetl.core.resource_locator import (
        dataset_locator,
        parse_noetl_locator,
        partition_locator,
        stream_locator,
    )

    for builder, args in (
        (dataset_locator, ("acme", "research", "sales-2026")),
        (stream_locator, ("acme", "research", "orders-v1")),
        (partition_locator, ("acme", "research", "orders-v1", 3)),
    ):
        uri = builder(*args, region="us-east1", cluster_id="prod")
        locator = parse_noetl_locator(uri)
        # Tenant + org + locality are present
        assert locator.value_after("tenant") == "acme"
        assert locator.value_after("org") == "research"
        assert locator.value_after("region") == "us-east1"
        assert locator.value_after("cluster") == "prod"
