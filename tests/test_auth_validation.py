"""
Unit tests for the NoETL unified authentication validation.

Tests the auth_validation module's ability to validate authentication
configurations according to plugin-specific requirements and schema rules.
"""

import pytest
from noetl.worker.auth_validation import (
    validate_auth_for_plugin, validate_step_auth, 
    PLUGIN_AUTH_ARITY, AuthValidationError
)


class TestAuthValidation:
    """Test suite for the auth validation module."""
    
    def test_validate_single_auth_valid(self):
        """Test validation of valid single authentication configuration."""
        single_auth = {
            "type": "postgres",
            "credential": "pg_local"
        }
        
        # Should not raise any exceptions
        validate_auth_for_plugin(single_auth, "postgres", "single")
    
    def test_validate_multi_auth_valid(self):
        """Test validation of valid multi authentication configuration."""
        multi_auth = {
            "db": {
                "type": "postgres",
                "credential": "pg_main" 
            },
            "storage": {
                "type": "gcs",
                "inline": {
                    "key_id": "HMAC_KEY",
                    "secret_key": "HMAC_SECRET"
                }
            }
        }
        
        # Should not raise any exceptions
        validate_auth_for_plugin(multi_auth, "duckdb", "multi")
    
    def test_validate_single_auth_missing_type(self):
        """Test validation failure for single auth missing type."""
        single_auth = {
            "credential": "test_cred"  # Missing 'type' field
        }
        
        with pytest.raises(AuthValidationError, match="Single auth configuration missing 'type'"):
            validate_auth_for_plugin(single_auth, "postgres", "single")
    
    def test_validate_single_auth_missing_source(self):
        """Test validation failure for single auth missing source."""
        single_auth = {
            "type": "postgres"  # No credential, inline, env, or secret
        }
        
        with pytest.raises(AuthValidationError, match="Single auth configuration must specify exactly one source"):
            validate_auth_for_plugin(single_auth, "postgres", "single")
    
    def test_validate_single_auth_multiple_sources(self):
        """Test validation failure for single auth with multiple sources."""
        single_auth = {
            "type": "postgres",
            "credential": "test_cred",
            "inline": {"host": "localhost"},  # Multiple sources
            "env": "DB_URL"
        }
        
        with pytest.raises(AuthValidationError, match="Single auth configuration must specify exactly one source"):
            validate_auth_for_plugin(single_auth, "postgres", "single")
    
    def test_validate_multi_auth_reserved_key(self):
        """Test validation failure for multi auth using reserved alias."""
        multi_auth = {
            "type": {  # Reserved key 'type'
                "type": "postgres",
                "credential": "pg_main"
            },
            "storage": {
                "type": "gcs",
                "credential": "gcs_main"
            }
        }
        
        with pytest.raises(AuthValidationError, match="Auth alias 'type' is reserved"):
            validate_auth_for_plugin(multi_auth, "duckdb", "multi")
    
    def test_validate_multi_auth_all_reserved_keys(self):
        """Test validation failure for all reserved keys in multi auth."""
        reserved_keys = ["type", "credential", "secret", "env", "inline"]
        
        for reserved_key in reserved_keys:
            multi_auth = {
                reserved_key: {
                    "type": "postgres",
                    "credential": "test"
                }
            }
            
            with pytest.raises(AuthValidationError, match=f"Auth alias '{reserved_key}' is reserved"):
                validate_auth_for_plugin(multi_auth, "duckdb", "multi")
    
    def test_validate_multi_auth_nested_missing_type(self):
        """Test validation failure for multi auth with nested missing type."""
        multi_auth = {
            "db": {
                "credential": "pg_main"  # Missing 'type'
            }
        }
        
        with pytest.raises(AuthValidationError, match="Auth alias 'db' missing 'type'"):
            validate_auth_for_plugin(multi_auth, "duckdb", "multi")
    
    def test_validate_multi_auth_nested_multiple_sources(self):
        """Test validation failure for multi auth with nested multiple sources."""
        multi_auth = {
            "db": {
                "type": "postgres",
                "credential": "pg_main",
                "inline": {"host": "localhost"}  # Multiple sources
            }
        }
        
        with pytest.raises(AuthValidationError, match="Auth alias 'db' must specify exactly one source"):
            validate_auth_for_plugin(multi_auth, "duckdb", "multi")
    
    def test_validate_plugin_arity_mismatch_single_to_multi(self):
        """Test validation failure when plugin expects single but gets multi."""
        multi_auth = {
            "db": {
                "type": "postgres",
                "credential": "pg_main"
            }
        }
        
        with pytest.raises(AuthValidationError, match="Plugin 'postgres' expects single auth but received multi auth"):
            validate_auth_for_plugin(multi_auth, "postgres", "single")
    
    def test_validate_plugin_arity_mismatch_multi_to_single(self):
        """Test validation failure when plugin expects multi but gets single."""
        single_auth = {
            "type": "postgres",
            "credential": "pg_main"
        }
        
        with pytest.raises(AuthValidationError, match="Plugin 'duckdb' expects multi auth but received single auth"):
            validate_auth_for_plugin(single_auth, "duckdb", "multi")
    
    def test_validate_plugin_unknown_type(self):
        """Test validation with unknown plugin type (should not raise error)."""
        single_auth = {
            "type": "postgres",
            "credential": "test"
        }
        
        # Unknown plugin types should be validated permissively
        validate_auth_for_plugin(single_auth, "unknown_plugin", "single")
    
    def test_validate_step_auth_postgres_valid(self):
        """Test step-level validation for Postgres plugin."""
        step_config = {
            "task": "test_task",
            "type": "postgres",
            "auth": {
                "type": "postgres",
                "credential": "pg_local"
            }
        }
        
        # Should not raise any exceptions
        validate_step_auth(step_config)
    
    def test_validate_step_auth_duckdb_valid(self):
        """Test step-level validation for DuckDB plugin."""
        step_config = {
            "task": "test_task", 
            "type": "duckdb",
            "auth": {
                "db": {
                    "type": "postgres",
                    "credential": "pg_main"
                },
                "storage": {
                    "type": "gcs",
                    "credential": "gcs_main"
                }
            }
        }
        
        # Should not raise any exceptions
        validate_step_auth(step_config)
    
    def test_validate_step_auth_http_valid(self):
        """Test step-level validation for HTTP plugin."""
        step_config = {
            "task": "test_task",
            "type": "http", 
            "auth": {
                "type": "bearer",
                "env": "API_TOKEN"
            }
        }
        
        # Should not raise any exceptions
        validate_step_auth(step_config)
    
    def test_validate_step_auth_no_auth_field(self):
        """Test step validation when no auth field is present."""
        step_config = {
            "task": "test_task",
            "type": "postgres"
            # No 'auth' field
        }
        
        # Should not raise any exceptions when auth is optional
        validate_step_auth(step_config)
    
    def test_validate_step_auth_unknown_plugin_type(self):
        """Test step validation for unknown plugin type."""
        step_config = {
            "task": "test_task",
            "type": "unknown_type",
            "auth": {
                "type": "postgres",
                "credential": "test"
            }
        }
        
        # Should handle gracefully without errors
        validate_step_auth(step_config)
    
    def test_validate_step_auth_invalid_config(self):
        """Test step validation failure for invalid auth config."""
        step_config = {
            "task": "test_task",
            "type": "postgres",
            "auth": {
                # Missing 'type' and source fields
            }
        }
        
        with pytest.raises(AuthValidationError):
            validate_step_auth(step_config)
    
    def test_plugin_auth_arity_mappings(self):
        """Test that plugin auth arity mappings are correctly defined."""
        assert PLUGIN_AUTH_ARITY["postgres"] == "single"
        assert PLUGIN_AUTH_ARITY["http"] == "single"
        assert PLUGIN_AUTH_ARITY["duckdb"] == "multi"
        
        # Should handle missing plugins gracefully
        unknown_arity = PLUGIN_AUTH_ARITY.get("unknown_plugin")
        assert unknown_arity is None
    
    def test_validate_inline_auth_structure(self):
        """Test validation of inline auth configuration structure."""
        valid_inline_auth = {
            "type": "postgres",
            "inline": {
                "host": "localhost",
                "port": 5432,
                "user": "admin",
                "password": "secret",
                "database": "testdb"
            }
        }
        
        validate_auth_for_plugin(valid_inline_auth, "postgres", "single")
    
    def test_validate_credential_auth_structure(self):
        """Test validation of credential-based auth configuration."""
        valid_credential_auth = {
            "type": "postgres",
            "credential": "pg_production"
        }
        
        validate_auth_for_plugin(valid_credential_auth, "postgres", "single")
    
    def test_validate_env_auth_structure(self):
        """Test validation of environment-based auth configuration."""
        valid_env_auth = {
            "type": "bearer",
            "env": "API_TOKEN"
        }
        
        validate_auth_for_plugin(valid_env_auth, "http", "single")
    
    def test_validate_secret_auth_structure(self):
        """Test validation of secret manager auth configuration."""
        valid_secret_auth = {
            "type": "api_key",
            "secret": "projects/test/secrets/api-key/versions/latest"
        }
        
        validate_auth_for_plugin(valid_secret_auth, "http", "single")


if __name__ == "__main__":
    pytest.main([__file__])