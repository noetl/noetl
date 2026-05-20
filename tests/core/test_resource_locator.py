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
