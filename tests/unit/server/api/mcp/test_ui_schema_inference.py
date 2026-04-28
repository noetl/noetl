"""Tests for the workload form inference (api/mcp/ui_schema.py)."""

from __future__ import annotations

import textwrap

import pytest

from noetl.server.api.mcp.ui_schema import infer_ui_schema


def test_returns_empty_for_yaml_without_workload():
    assert infer_ui_schema("apiVersion: noetl.io/v2\nkind: Playbook\n") == []


def test_infers_basic_field_types_from_defaults():
    yaml = textwrap.dedent(
        """
        workload:
          name: alice
          replicas: 3
          ratio: 0.5
          enabled: true
          tags:
            - a
            - b
          extras: {}
          empty: ~
        """
    )
    fields = infer_ui_schema(yaml)
    by_name = {f.name: f for f in fields}

    assert by_name["name"].kind == "string"
    assert by_name["replicas"].kind == "integer"
    assert by_name["ratio"].kind == "number"
    assert by_name["enabled"].kind == "boolean"
    assert by_name["tags"].kind == "array"
    assert by_name["extras"].kind == "object"
    assert by_name["empty"].kind == "null"


def test_recurses_into_nested_objects():
    yaml = textwrap.dedent(
        """
        workload:
          db:
            host: localhost
            port: 5432
        """
    )
    fields = infer_ui_schema(yaml)
    assert len(fields) == 1
    db_field = fields[0]
    assert db_field.kind == "object"
    assert db_field.children is not None
    child_kinds = {c.name: c.kind for c in db_field.children}
    assert child_kinds == {"host": "string", "port": "integer"}


def test_ui_directive_secret_marks_field():
    yaml = textwrap.dedent(
        """
        workload:
          api_key: "" # ui:secret
          username: alice
        """
    )
    fields = {f.name: f for f in infer_ui_schema(yaml)}
    assert fields["api_key"].secret is True
    assert fields["username"].secret is False


def test_ui_directive_enum_overrides_kind():
    yaml = textwrap.dedent(
        """
        workload:
          mode: read-only # ui:enum=[read-only,read-write]
        """
    )
    field = infer_ui_schema(yaml)[0]
    assert field.kind == "enum"
    assert field.options == ["read-only", "read-write"]


def test_ui_directive_credential_filter():
    yaml = textwrap.dedent(
        """
        workload:
          db_auth: pg_default # ui:credential=pg_*
        """
    )
    field = infer_ui_schema(yaml)[0]
    assert field.credential_glob == "pg_*"


def test_handles_invalid_yaml_gracefully():
    assert infer_ui_schema("workload:\n  - this is not a mapping") == []
    assert infer_ui_schema("::not yaml::") == []


def test_ignores_unknown_directives():
    yaml = textwrap.dedent(
        """
        workload:
          name: alice # ui:weird=foo
        """
    )
    field = infer_ui_schema(yaml)[0]
    assert field.kind == "string"
    assert field.secret is False


def test_multiple_directives_on_one_line_are_all_parsed():
    yaml = textwrap.dedent(
        """
        workload:
          api_key: "" # ui:secret # ui:description=API key for upstream
        """
    )
    field = infer_ui_schema(yaml)[0]
    assert field.secret is True
    assert field.description == "API key for upstream"


def test_four_space_indent_is_recognised():
    yaml = textwrap.dedent(
        """
        workload:
            api_key: "" # ui:secret
            username: alice
        """
    )
    fields = {f.name: f for f in infer_ui_schema(yaml)}
    assert fields["api_key"].secret is True
    assert fields["username"].kind == "string"
