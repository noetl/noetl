from noetl.server.api.catalog.schema import CatalogAgentsRequest, CatalogEntriesRequest
from noetl.server.api.catalog.service import CatalogService


def test_catalog_entries_request_normalizes_capability_into_capabilities():
    req = CatalogEntriesRequest(capability="code-review")
    assert req.agent_only is True
    assert req.capabilities == ["code-review"]


def test_catalog_entries_request_merges_capabilities_without_duplicates():
    req = CatalogEntriesRequest(
        capability="code-review",
        capabilities=["security-audit", "code-review"],
    )
    assert req.agent_only is True
    assert req.capabilities == ["security-audit", "code-review"]


def test_catalog_query_builder_includes_agent_filters():
    query, params = CatalogService._build_query_filter(
        resource_type="Playbook",
        path="agents/release-coordinator",
        agent_only=True,
        capabilities=["release-management", "deployment"],
    )

    assert "lower(c.kind) = %(resource_type)s" in query
    assert "c.path = %(path)s" in query
    assert "payload->'metadata'->>'agent'" in query
    assert "c.meta->>'agent'" in query
    assert "jsonb_array_elements_text" in query
    assert "jsonb_typeof" in query
    assert "capabilities" in params
    assert params["resource_type"] == "playbook"
    assert params["path"] == "agents/release-coordinator"
    assert params["capabilities"] == ["release-management", "deployment"]


def test_catalog_query_builder_can_discover_agents_across_resource_kinds():
    query, params = CatalogService._build_query_filter(
        resource_type=None,
        agent_only=True,
        capabilities=["mcp:kubernetes"],
    )

    assert "c.kind = %(resource_type)s" not in query
    assert "payload->'metadata'->>'agent'" in query
    assert params["capabilities"] == ["mcp:kubernetes"]


def test_catalog_agents_request_normalizes_capabilities():
    req = CatalogAgentsRequest(capability="code-review", capabilities=["security-audit"])
    assert req.capabilities == ["security-audit", "code-review"]


def test_extract_agent_metadata_normalizes_string_capability():
    metadata = CatalogService._extract_agent_metadata(
        {"metadata": {"agent": "yes", "capabilities": "release-management"}}
    )
    assert metadata["agent"] is True
    assert metadata["capabilities"] == ["release-management"]


def test_extract_agent_metadata_preserves_terminal_scopes():
    metadata = CatalogService._extract_agent_metadata(
        {
            "metadata": {
                "agent": True,
                "terminal": {
                    "visible": True,
                    "workspace": "kubernetes",
                    "scopes": ["/mcp/kubernetes"],
                },
            }
        }
    )

    assert metadata["terminal_visible"] is True
    assert metadata["terminal"]["workspace"] == "kubernetes"
    assert metadata["terminal_scopes"] == ["/mcp/kubernetes"]
