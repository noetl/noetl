"""
Test suite for DuckDB secret prelude functionality.

Tests the new credential alias system that allows DuckDB steps to contain
credentials: { alias: { key: <credential_key>, scope: "gs://{{ var }}" } }
and auto-generates CREATE SECRET statements.
"""

import pytest
from jinja2 import Environment
import noetl.plugin.duckdb as ddb


def test_build_duckdb_secret_prelude_gcs_pg():
    """Test GCS + Postgres happy path with Jinja scope rendering."""
    
    def fake_fetch(key):
        if key == "gcs_hmac_local":
            return {
                "service": "gcs",
                "data_source": "credstore",
                "key_id": "GOOG123",
                "secret_key": "SECR456"
            }
        if key == "pg_local":
            return {
                "service": "postgres",
                "db_host": "localhost",
                "db_port": 5432,
                "db_name": "demo",
                "db_user": "demo",
                "db_password": "s3cr3t"
            }
        raise RuntimeError("not found")

    jenv = Environment()
    context = {
        "workload": { "gcs_bucket": "noetl-demo-19700101" }
    }

    task_config = {
        "type": "duckdb",
        "credentials": {
            "gcs_secret": { "key": "gcs_hmac_local", "scope": "gs://{{ workload.gcs_bucket }}" },
            "pg_db":      { "key": "pg_local" }
        }
    }
    params = {
        "output_uri_base": "gs://noetl-demo-19700101/weather"
    }

    prelude = ddb._build_duckdb_secret_prelude(task_config, params, jenv, context, fake_fetch)

    # Must install both httpfs and postgres extensions first
    assert any(s.startswith("INSTALL httpfs;") for s in prelude)
    assert any(s.startswith("INSTALL postgres;") for s in prelude)

    # Expect CREATE SECRET for GCS with resolved scope and HMAC fields
    gcs_stmt = "\n".join([s for s in prelude if "TYPE gcs" in s])
    assert "CREATE OR REPLACE SECRET gcs_secret" in gcs_stmt
    assert "KEY_ID 'GOOG123'" in gcs_stmt
    assert "SECRET 'SECR456'" in gcs_stmt
    assert "SCOPE 'gs://noetl-demo-19700101'" in gcs_stmt  # Jinja rendered

    # Expect CREATE SECRET for Postgres
    pg_stmt = "\n".join([s for s in prelude if "TYPE postgres" in s])
    assert "CREATE OR REPLACE SECRET pg_db" in pg_stmt
    assert "HOST 'localhost'" in pg_stmt
    assert "PORT 5432" in pg_stmt
    assert "DATABASE 'demo'" in pg_stmt
    assert "USER 'demo'" in pg_stmt
    assert "PASSWORD '" in pg_stmt


def test_build_duckdb_secret_prelude_gcs_missing_keys():
    """Test that GCS missing HMAC keys raises appropriate error."""
    
    def fake_fetch(key):
        return { "service": "gcs" }  # missing key_id/secret_key

    jenv = Environment()
    
    with pytest.raises(ValueError, match="missing key_id/secret_key"):
        ddb._build_duckdb_secret_prelude(
            task_config={
                "type": "duckdb",
                "credentials": { "gcs": { "key": "gcs_hmac_local" } }
            },
            params={"output_uri_base": "gs://bucket/path"},
            jinja_env=jenv,
            context={},
            fetch_fn=fake_fetch
        )


def test_build_duckdb_secret_prelude_postgres_missing_fields():
    """Test that Postgres missing required fields raises appropriate error."""
    
    def fake_fetch(key):
        return { 
            "service": "postgres", 
            "db_host": "localhost",
            # Missing db_name, db_user, db_password
        }

    jenv = Environment()
    
    with pytest.raises(ValueError, match="incomplete"):
        ddb._build_duckdb_secret_prelude(
            task_config={
                "type": "duckdb",
                "credentials": { "pg_db": { "key": "pg_local" } }
            },
            params={},
            jinja_env=jenv,
            context={},
            fetch_fn=fake_fetch
        )


def test_build_duckdb_secret_prelude_scope_inference():
    """Test that GCS scope can be inferred from output_uri_base."""
    
    def fake_fetch(key):
        return {
            "service": "gcs",
            "key_id": "GOOG123",
            "secret_key": "SECR456"
            # No explicit scope
        }

    jenv = Environment()
    
    prelude = ddb._build_duckdb_secret_prelude(
        task_config={
            "type": "duckdb",
            "credentials": { "gcs_secret": { "key": "gcs_hmac_local" } }
        },
        params={"output_uri_base": "gs://test-bucket/path"},
        jinja_env=jenv,
        context={},
        fetch_fn=fake_fetch
    )

    # Should infer scope from output_uri_base
    gcs_stmt = "\n".join([s for s in prelude if "TYPE gcs" in s])
    assert "SCOPE 'gs://test-bucket'" in gcs_stmt


def test_build_duckdb_secret_prelude_with_overrides():
    """Test that 'with' credentials take precedence over step credentials."""
    
    def fake_fetch(key):
        if key == "override_key":
            return {
                "service": "gcs",
                "key_id": "OVERRIDE123",
                "secret_key": "OVERRIDE456"
            }
        return {}

    jenv = Environment()
    
    task_config = {
        "credentials": {
            "gcs_secret": { "key": "original_key", "scope": "gs://original" }
        }
    }
    params = {
        "credentials": {
            "gcs_secret": { "key": "override_key", "scope": "gs://override" }
        }
    }

    prelude = ddb._build_duckdb_secret_prelude(task_config, params, jenv, {}, fake_fetch)

    # Should use the override from params
    gcs_stmt = "\n".join([s for s in prelude if "TYPE gcs" in s])
    assert "KEY_ID 'OVERRIDE123'" in gcs_stmt
    assert "SCOPE 'gs://override'" in gcs_stmt


def test_render_deep():
    """Test deep template rendering utility."""
    jenv = Environment()
    context = {"bucket": "test-bucket"}
    
    obj = {
        "simple": "gs://{{ bucket }}",
        "nested": {
            "path": "gs://{{ bucket }}/data"
        },
        "list": ["gs://{{ bucket }}/a", "gs://{{ bucket }}/b"]
    }
    
    result = ddb._render_deep(jenv, context, obj)
    
    assert result["simple"] == "gs://test-bucket"
    assert result["nested"]["path"] == "gs://test-bucket/data"
    assert result["list"][0] == "gs://test-bucket/a"
    assert result["list"][1] == "gs://test-bucket/b"


def test_escape_sql():
    """Test SQL escaping utility."""
    assert ddb._escape_sql("test") == "test"
    assert ddb._escape_sql("test'quote") == "test''quote"
    assert ddb._escape_sql("multiple'quotes'here") == "multiple''quotes''here"
    assert ddb._escape_sql(None) == ""