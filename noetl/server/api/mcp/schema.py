"""Schemas for the MCP server lifecycle / discovery / ui_schema API."""

from datetime import datetime
from typing import Any, Optional
from pydantic import Field, field_validator, model_validator

from noetl.core.common import AppBaseModel


# ---------------------------------------------------------------------------
# Lifecycle dispatch
# ---------------------------------------------------------------------------


class McpLifecycleRequest(AppBaseModel):
    """Trigger a lifecycle verb on a registered Mcp catalog resource.

    The Mcp resource's spec.lifecycle.{verb} field resolves to an Agent
    playbook path. The endpoint dispatches that agent via /api/execute,
    passing the Mcp resource (path + version + payload) as workload so
    the agent has everything it needs to deploy / restart / etc.
    """

    workload_overrides: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Overrides merged onto the lifecycle agent's workload. "
            "Use sparingly; most callers should rely on the resource's "
            "own spec values."
        ),
    )
    version: Optional[str | int] = Field(
        default="latest",
        description="Mcp resource version (default 'latest')",
    )


class McpLifecycleResponse(AppBaseModel):
    """Result of a lifecycle dispatch -- pointer to the started run."""

    status: str = Field(description="'started' on success", example="started")
    verb: str = Field(description="The lifecycle verb that was dispatched")
    mcp_path: str = Field(description="The Mcp resource path")
    mcp_version: int = Field(description="The Mcp resource version")
    agent_path: str = Field(description="Agent playbook path resolved")
    execution_id: str = Field(description="Started agent execution id")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class McpDiscoverRequest(AppBaseModel):
    """Refresh the Mcp resource's tool list.

    Two strategies, in priority order:
    1. spec.discovery.refresh_via -- run the named Agent playbook,
       expect the agent's output to contain a `tools` array, and patch
       it onto the catalog entry.
    2. spec.discovery.tools_list_url -- fetch the URL directly, parse
       the response as JSON, expect `tools` array.

    If neither is configured, returns 422.
    """

    version: Optional[str | int] = Field(
        default="latest",
        description="Mcp resource version (default 'latest')",
    )
    force: bool = Field(
        default=False,
        description=(
            "If true, register a new catalog version even when the tool "
            "list hasn't changed. Default false (only re-register on diff)."
        ),
    )


class McpDiscoverResponse(AppBaseModel):
    """Discovery outcome -- one of agent_dispatched / direct_fetch."""

    status: str = Field(description="'started' or 'updated'")
    mcp_path: str = Field(description="The Mcp resource path")
    mcp_version_old: int = Field(description="Version that was inspected")
    mcp_version_new: Optional[int] = Field(
        default=None,
        description="New catalog version if tool list changed; null otherwise",
    )
    strategy: str = Field(
        description="Which discovery path was used: 'agent' or 'direct'",
    )
    execution_id: Optional[str] = Field(
        default=None,
        description="Agent execution id (only when strategy='agent')",
    )
    tool_count_before: Optional[int] = Field(
        default=None,
        description="Number of tools before refresh",
    )
    tool_count_after: Optional[int] = Field(
        default=None,
        description="Number of tools after refresh (only when strategy='direct')",
    )


# ---------------------------------------------------------------------------
# UI schema inference
# ---------------------------------------------------------------------------


class UiSchemaField(AppBaseModel):
    """One workload field inferred from a playbook's YAML.

    The inference rules (see service.infer_ui_schema):
    - Default-value type drives `kind`: string, number, integer, boolean,
      object, array, null.
    - Adjacent `# ui:enum=[...]` comment forces `kind=enum` and populates
      `options`.
    - `# ui:secret` flag marks the field as sensitive (mask in UI).
    - `# ui:credential=pg_*` constrains the field to a credential picker
      filtered by the given glob.
    - `# ui:description=...` sets the field description.
    - Nested objects produce nested fields in `children`.
    """

    name: str = Field(description="Workload key")
    kind: str = Field(
        description="Field kind: string|integer|number|boolean|object|array|null|enum",
    )
    default: Any = Field(default=None, description="Default value parsed from YAML")
    description: Optional[str] = Field(
        default=None,
        description="Human-readable hint, taken from `# ui:description=...` comment",
    )
    secret: bool = Field(
        default=False,
        description="True when `# ui:secret` directive is present",
    )
    credential_glob: Optional[str] = Field(
        default=None,
        description="Credential picker filter, e.g. 'pg_*'",
    )
    options: Optional[list[Any]] = Field(
        default=None,
        description="Enum options, when kind=enum",
    )
    children: Optional[list["UiSchemaField"]] = Field(
        default=None,
        description="Nested fields when kind=object",
    )


UiSchemaField.model_rebuild()


class UiSchemaResponse(AppBaseModel):
    """Inferred workload form for a catalog resource (Playbook or Agent)."""

    path: str = Field(description="Catalog path")
    version: int = Field(description="Catalog version inspected")
    kind: str = Field(description="Resource kind (Playbook | Agent | Mcp)")
    title: Optional[str] = Field(
        default=None,
        description="metadata.name from the resource",
    )
    description_markdown: Optional[str] = Field(
        default=None,
        description="metadata.description rendered as markdown source",
    )
    exposed_in_ui: bool = Field(
        default=False,
        description="True when metadata.exposed_in_ui is set on the resource",
    )
    fields: list[UiSchemaField] = Field(
        default_factory=list,
        description="Top-level workload fields",
    )
    generated_at: datetime = Field(description="Inference timestamp (UTC)")


# ---------------------------------------------------------------------------
# Validation helpers (re-used across endpoints)
# ---------------------------------------------------------------------------


KNOWN_LIFECYCLE_VERBS: tuple[str, ...] = (
    "deploy",
    "redeploy",
    "undeploy",
    "status",
    "restart",
    "discover",
)


def coerce_lifecycle_verb(verb: str) -> str:
    """Normalize and validate the verb path component."""
    cleaned = (verb or "").strip().lower()
    if not cleaned:
        raise ValueError("lifecycle verb cannot be empty")
    if cleaned not in KNOWN_LIFECYCLE_VERBS:
        # We don't hard-block unknown verbs at the schema layer; the
        # service tests resource.spec.lifecycle.{verb} and 422s if the
        # author hasn't wired it. Schema-level whitelist would prevent
        # custom verbs (e.g. "smoke-test"), which we want to allow.
        pass
    return cleaned
