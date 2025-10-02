"""
Unit tests for the NoETL unified authentication resolver.

Tests the auth_resolver module's ability to resolve various authentication
configurations including credential store lookups, environment variables,
secrets manager integration, and inline configurations.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from jinja2 import Environment

from noetl.worker.auth_resolver import resolve_auth, ResolvedAuthItem


class TestAuthResolver:
    """Test suite for the auth resolver module."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.jinja_env = Environment()
        self.context = {"execution_id": "test-123", "user": "testuser"}
    
    def test_resolve_single_credential_auth(self):
        """Test resolving single auth from credential store."""
        auth_config = {
            "type": "postgres",
            "credential": "pg_test"
        }
        
        with patch('noetl.worker.auth_resolver.fetch_credential_by_key') as mock_fetch:
            mock_fetch.return_value = {
                "host": "localhost",
                "port": 5432,
                "user": "testuser",
                "password": "testpass",
                "database": "testdb"
            }
            
            result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
            
            assert result is not None
            assert result.auth_type == "postgres"
            assert result.config["host"] == "localhost"
            assert result.config["port"] == 5432
            mock_fetch.assert_called_once_with("pg_test")
    
    def test_resolve_single_inline_auth(self):
        """Test resolving single inline authentication configuration."""
        auth_config = {
            "type": "postgres",
            "inline": {
                "host": "{{ user }}.example.com",
                "port": 5432,
                "user": "admin",
                "password": "secret123",
                "database": "prod"
            }
        }
        
        result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
        
        assert result is not None
        assert result.auth_type == "postgres"
        assert result.config["host"] == "testuser.example.com"  # Template rendered
        assert result.config["user"] == "admin"
        assert result.config["password"] == "secret123"
    
    def test_resolve_single_env_auth(self):
        """Test resolving single auth from environment variables."""
        auth_config = {
            "type": "bearer",
            "env": "API_TOKEN"
        }
        
        with patch.dict(os.environ, {"API_TOKEN": "bearer-token-123"}):
            result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
            
            assert result is not None
            assert result.auth_type == "bearer"
            assert result.config["token"] == "bearer-token-123"
    
    def test_resolve_single_secret_auth(self):
        """Test resolving single auth from secret manager."""
        auth_config = {
            "type": "api_key",
            "secret": "projects/test/secrets/api-key/versions/latest"
        }
        
        with patch('noetl.worker.auth_resolver.fetch_secret_manager_value') as mock_fetch:
            mock_fetch.return_value = {"key": "X-API-Key", "value": "secret-api-key"}
            
            result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
            
            assert result is not None
            assert result.auth_type == "api_key"
            assert result.config["key"] == "X-API-Key"
            assert result.config["value"] == "secret-api-key"
    
    def test_resolve_multi_auth_map(self):
        """Test resolving multiple authentication configurations."""
        auth_config = {
            "db": {
                "type": "postgres",
                "credential": "pg_main"
            },
            "storage": {
                "type": "gcs",
                "inline": {
                    "key_id": "HMAC_KEY_ID",
                    "secret_key": "HMAC_SECRET"
                }
            },
            "api": {
                "type": "bearer",
                "env": "API_TOKEN"
            }
        }
        
        with patch('noetl.worker.auth_resolver.fetch_credential_by_key') as mock_fetch:
            mock_fetch.return_value = {
                "host": "db.example.com",
                "port": 5432,
                "user": "dbuser",
                "password": "dbpass",
                "database": "maindb"
            }
            
            with patch.dict(os.environ, {"API_TOKEN": "api-token-456"}):
                result = resolve_auth(auth_config, self.context, self.jinja_env, mode='multi')
                
                assert isinstance(result, dict)
                assert len(result) == 3
                
                # Check postgres auth
                assert "db" in result
                db_auth = result["db"]
                assert db_auth.auth_type == "postgres"
                assert db_auth.config["host"] == "db.example.com"
                
                # Check GCS auth
                assert "storage" in result
                gcs_auth = result["storage"]
                assert gcs_auth.auth_type == "gcs"
                assert gcs_auth.config["key_id"] == "HMAC_KEY_ID"
                
                # Check Bearer auth
                assert "api" in result
                api_auth = result["api"]
                assert api_auth.auth_type == "bearer"
                assert api_auth.config["token"] == "api-token-456"
    
    def test_resolve_auth_with_jinja_templates(self):
        """Test auth resolution with complex Jinja template rendering."""
        auth_config = {
            "type": "postgres",
            "inline": {
                "host": "{{ execution_id }}.db.example.com",
                "port": "{{ 5432 + 10 }}",
                "user": "user_{{ user }}",
                "password": "{{ 'secret' + '_' + execution_id[-3:] }}",
                "database": "db_{{ user }}"
            }
        }
        
        result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
        
        assert result is not None
        assert result.config["host"] == "test-123.db.example.com"
        assert result.config["port"] == 5442  # 5432 + 10
        assert result.config["user"] == "user_testuser"
        assert result.config["password"] == "secret_123"  # last 3 chars of execution_id
        assert result.config["database"] == "db_testuser"
    
    def test_resolve_auth_field_override_priority(self):
        """Test that inline fields override credential fields properly."""
        auth_config = {
            "type": "postgres",
            "credential": "pg_base",
            "inline": {
                "password": "override_password",  # Should override credential password
                "port": 3306  # Should override credential port
            }
        }
        
        with patch('noetl.worker.auth_resolver.fetch_credential_by_key') as mock_fetch:
            mock_fetch.return_value = {
                "host": "credential_host",
                "port": 5432,
                "user": "credential_user", 
                "password": "credential_password",
                "database": "credential_db"
            }
            
            result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
            
            assert result is not None
            assert result.config["host"] == "credential_host"  # From credential
            assert result.config["user"] == "credential_user"  # From credential
            assert result.config["database"] == "credential_db"  # From credential
            assert result.config["password"] == "override_password"  # Overridden
            assert result.config["port"] == 3306  # Overridden
    
    def test_resolve_auth_invalid_mode(self):
        """Test error handling for invalid resolution mode."""
        auth_config = {"type": "postgres", "inline": {"host": "localhost"}}
        
        with pytest.raises(ValueError, match="mode must be 'single' or 'multi'"):
            resolve_auth(auth_config, self.context, self.jinja_env, mode='invalid')
    
    def test_resolve_auth_missing_type(self):
        """Test error handling when auth type is missing."""
        auth_config = {"credential": "test_cred"}  # No 'type' field
        
        with pytest.raises(ValueError, match="Auth configuration missing 'type'"):
            resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
    
    def test_resolve_auth_missing_source(self):
        """Test error handling when no auth source is specified."""
        auth_config = {"type": "postgres"}  # No credential, inline, env, or secret
        
        with pytest.raises(ValueError, match="Auth configuration must specify one source"):
            resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
    
    def test_resolve_auth_multiple_sources(self):
        """Test error handling when multiple auth sources are specified."""
        auth_config = {
            "type": "postgres",
            "credential": "test_cred",
            "inline": {"host": "localhost"},  # Multiple sources
            "env": "DB_CONFIG"
        }
        
        with pytest.raises(ValueError, match="Auth configuration must specify exactly one source"):
            resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
    
    def test_resolve_auth_credential_fetch_failure(self):
        """Test handling of credential fetch failures."""
        auth_config = {
            "type": "postgres",
            "credential": "nonexistent_key"
        }
        
        with patch('noetl.worker.auth_resolver.fetch_credential_by_key') as mock_fetch:
            mock_fetch.side_effect = Exception("Credential not found")
            
            with pytest.raises(Exception, match="Failed to fetch credential 'nonexistent_key'"):
                resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
    
    def test_resolve_auth_env_var_missing(self):
        """Test handling of missing environment variables."""
        auth_config = {
            "type": "bearer",
            "env": "MISSING_ENV_VAR"
        }
        
        with pytest.raises(ValueError, match="Environment variable 'MISSING_ENV_VAR' not found"):
            resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
    
    def test_resolve_auth_secret_redaction(self):
        """Test that sensitive fields are properly redacted in ResolvedAuthItem."""
        auth_config = {
            "type": "postgres",
            "inline": {
                "host": "localhost",
                "user": "admin",
                "password": "sensitive_password",
                "database": "testdb"
            }
        }
        
        result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
        
        assert result is not None
        # The actual config should contain the real password
        assert result.config["password"] == "sensitive_password"
        
        # String representation should be redacted
        str_repr = str(result)
        assert "sensitive_password" not in str_repr
        assert "[REDACTED]" in str_repr
    
    def test_resolved_auth_item_equality(self):
        """Test ResolvedAuthItem equality comparison."""
        item1 = ResolvedAuthItem(
            auth_type="postgres",
            config={"host": "localhost", "password": "secret"}
        )
        
        item2 = ResolvedAuthItem(
            auth_type="postgres", 
            config={"host": "localhost", "password": "secret"}
        )
        
        item3 = ResolvedAuthItem(
            auth_type="postgres",
            config={"host": "remotehost", "password": "secret"}
        )
        
        assert item1 == item2
        assert item1 != item3
        assert item1 != "not_an_auth_item"


if __name__ == "__main__":
    pytest.main([__file__])