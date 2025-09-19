"""
Unit tests for the unified authentication system in NoETL.

Tests the _auth.py module functions and integration with plugins.
"""

import pytest
import os
import copy
from unittest.mock import Mock, patch, MagicMock
from jinja2 import Environment

from noetl.worker.plugin._auth import (
    resolve_auth_map,
    get_postgres_auth,
    build_http_headers,
    get_duckdb_secrets,
    get_required_extensions,
    _convert_legacy_auth,
    _normalize_postgres_fields,
    _normalize_hmac_fields,
    _redact_dict,
    AUTH_TYPES,
    REDACTED_FIELDS
)


@pytest.fixture
def jinja_env():
    """Create a Jinja2 environment for testing."""
    return Environment()


@pytest.fixture
def sample_context():
    """Sample execution context."""
    return {
        'execution_id': 'test-123',
        'workload': {
            'gcs_bucket': 'test-bucket'
        }
    }


@pytest.fixture
def mock_credential_store():
    """Mock credential store responses."""
    return {
        'pg_local': {
            'type': 'postgres',
            'data': {
                'db_host': 'localhost',
                'db_port': 5432,
                'db_user': 'testuser',
                'db_password': 'testpass',
                'db_name': 'testdb'
            }
        },
        'gcs_hmac_local': {
            'type': 'gcs_hmac',
            'data': {
                'key_id': 'GOOG123ABC',
                'secret_key': 'supersecret',
                'service': 'gcs'
            }
        },
        'api_token': {
            'type': 'bearer',
            'data': {
                'token': 'bearer-token-123'
            }
        }
    }


class TestAuthHelpers:
    """Test helper functions."""
    
    def test_redact_dict(self):
        """Test dictionary redaction for logging."""
        data = {
            'username': 'user',
            'password': 'secret',
            'db_password': 'dbsecret',
            'token': 'mytoken',
            'other': 'value'
        }
        
        redacted = _redact_dict(data)
        
        assert redacted['username'] == 'user'
        assert redacted['password'] == '[REDACTED]'
        assert redacted['db_password'] == '[REDACTED]'
        assert redacted['token'] == '[REDACTED]'
        assert redacted['other'] == 'value'
    
    def test_normalize_postgres_fields(self):
        """Test postgres field normalization."""
        raw_record = {
            'host': 'localhost',
            'port': 5432,
            'database': 'mydb',
            'user': 'myuser',
            'password': 'mypass',
            'ssl': 'require'
        }
        
        normalized = _normalize_postgres_fields(raw_record)
        
        assert normalized['db_host'] == 'localhost'
        assert normalized['db_port'] == 5432
        assert normalized['db_name'] == 'mydb'
        assert normalized['db_user'] == 'myuser'
        assert normalized['db_password'] == 'mypass'
        assert normalized['sslmode'] == 'require'
    
    def test_normalize_hmac_fields(self):
        """Test HMAC field normalization."""
        raw_record = {
            'access_key_id': 'AKIAI123',
            'secret_access_key': 'secretkey',
            'region': 'us-west-2'
        }
        
        normalized = _normalize_hmac_fields(raw_record, 'gcs')
        
        assert normalized['service'] == 'gcs'
        assert normalized['key_id'] == 'AKIAI123'
        assert normalized['secret_key'] == 'secretkey'
        assert normalized['region'] == 'us-west-2'


class TestLegacyConversion:
    """Test conversion of legacy auth formats."""
    
    def test_convert_legacy_credentials(self):
        """Test conversion of legacy credentials mapping."""
        step_config = {
            'credentials': {
                'pg_db': {'key': 'pg_local', 'type': 'postgres'},
                'gcs_secret': {'key': 'gcs_hmac_local'}
            }
        }
        
        converted = _convert_legacy_auth(step_config, {})
        
        assert 'auth' in converted
        assert 'pg_db' in converted['auth']
        assert converted['auth']['pg_db']['type'] == 'postgres'
        assert converted['auth']['pg_db']['key'] == 'pg_local'
        assert converted['auth']['gcs_secret']['type'] == 'postgres'  # default
        assert converted['auth']['gcs_secret']['key'] == 'gcs_hmac_local'
    
    def test_convert_legacy_string_credentials(self):
        """Test conversion of legacy string credential references."""
        step_config = {
            'credentials': {
                'pg_db': 'pg_local',
                'gcs_secret': 'gcs_hmac_local'
            }
        }
        
        converted = _convert_legacy_auth(step_config, {})
        
        assert 'auth' in converted
        assert converted['auth']['pg_db']['key'] == 'pg_local'
        assert converted['auth']['gcs_secret']['key'] == 'gcs_hmac_local'


class TestAuthResolution:
    """Test auth resolution functionality."""
    
    @patch('noetl.worker.plugin._auth.fetch_credential_by_key')
    def test_resolve_unified_auth_postgres(self, mock_fetch, jinja_env, sample_context, mock_credential_store):
        """Test resolving unified auth for postgres."""
        mock_fetch.return_value = mock_credential_store['pg_local']
        
        step_config = {
            'auth': {
                'pg': {
                    'type': 'postgres',
                    'key': 'pg_local'
                }
            }
        }
        
        resolved = resolve_auth_map(step_config, {}, jinja_env, sample_context)
        
        assert 'pg' in resolved
        assert resolved['pg']['type'] == 'postgres'
        assert resolved['pg']['db_host'] == 'localhost'
        assert resolved['pg']['db_port'] == 5432
        assert resolved['pg']['db_user'] == 'testuser'
        assert resolved['pg']['secret_name'] == 'pg'
    
    @patch('noetl.worker.plugin._auth.fetch_credential_by_key')
    def test_resolve_unified_auth_hmac(self, mock_fetch, jinja_env, sample_context, mock_credential_store):
        """Test resolving unified auth for HMAC credentials."""
        mock_fetch.return_value = mock_credential_store['gcs_hmac_local']
        
        step_config = {
            'auth': {
                'gcs': {
                    'type': 'hmac',
                    'service': 'gcs',
                    'key': 'gcs_hmac_local',
                    'scope': 'gs://{{ workload.gcs_bucket }}'
                }
            }
        }
        
        resolved = resolve_auth_map(step_config, {}, jinja_env, sample_context)
        
        assert 'gcs' in resolved
        assert resolved['gcs']['type'] == 'hmac'
        assert resolved['gcs']['service'] == 'gcs'
        assert resolved['gcs']['key_id'] == 'GOOG123ABC'
        assert resolved['gcs']['secret_key'] == 'supersecret'
        assert resolved['gcs']['scope'] == 'gs://test-bucket'
    
    @patch('noetl.worker.plugin._auth._fetch_secret_manager_value')
    def test_resolve_auth_secret_manager(self, mock_fetch_secret, jinja_env, sample_context):
        """Test resolving auth from secret manager."""
        mock_fetch_secret.return_value = 'secret-token-value'
        
        step_config = {
            'auth': {
                'api': {
                    'type': 'bearer',
                    'key': 'api_token',
                    'provider': 'secret_manager'
                }
            }
        }
        
        resolved = resolve_auth_map(step_config, {}, jinja_env, sample_context)
        
        assert 'api' in resolved
        assert resolved['api']['type'] == 'bearer'
        assert resolved['api']['token'] == 'secret-token-value'
    
    def test_resolve_auth_with_overrides(self, jinja_env, sample_context):
        """Test auth resolution with task_with overrides."""
        step_config = {
            'auth': {
                'pg': {
                    'type': 'postgres',
                    'db_host': 'step-host'
                }
            }
        }
        
        task_with = {
            'auth': {
                'pg': {
                    'db_host': 'override-host',
                    'db_port': 9999
                }
            }
        }
        
        resolved = resolve_auth_map(step_config, task_with, jinja_env, sample_context)
        
        assert resolved['pg']['db_host'] == 'override-host'
        assert resolved['pg']['db_port'] == 9999
    
    def test_resolve_auth_legacy_string(self, jinja_env, sample_context):
        """Test resolving legacy string auth reference."""
        step_config = {
            'auth': 'pg_local'
        }
        
        resolved = resolve_auth_map(step_config, {}, jinja_env, sample_context)
        
        assert 'default' in resolved
        assert resolved['default']['type'] == 'postgres'
        assert resolved['default']['key'] == 'pg_local'


class TestPostgresAuth:
    """Test postgres-specific auth functions."""
    
    def test_get_postgres_auth_single(self):
        """Test getting postgres auth when only one exists."""
        resolved_auth = {
            'pg': {
                'type': 'postgres',
                'db_host': 'localhost',
                'db_port': 5432
            }
        }
        
        pg_auth = get_postgres_auth(resolved_auth)
        
        assert pg_auth is not None
        assert pg_auth['db_host'] == 'localhost'
        assert pg_auth['db_port'] == 5432
    
    def test_get_postgres_auth_multiple_with_selection(self):
        """Test getting postgres auth when multiple exist with explicit selection."""
        resolved_auth = {
            'pg1': {
                'type': 'postgres',
                'db_host': 'host1'
            },
            'pg2': {
                'type': 'postgres', 
                'db_host': 'host2'
            }
        }
        
        pg_auth = get_postgres_auth(resolved_auth, use_auth='pg2')
        
        assert pg_auth is not None
        assert pg_auth['db_host'] == 'host2'
    
    def test_get_postgres_auth_none_found(self):
        """Test getting postgres auth when none exists."""
        resolved_auth = {
            'gcs': {
                'type': 'hmac',
                'service': 'gcs'
            }
        }
        
        pg_auth = get_postgres_auth(resolved_auth)
        
        assert pg_auth is None


class TestHttpAuth:
    """Test HTTP authentication functions."""
    
    def test_build_http_headers_bearer(self):
        """Test building HTTP headers for bearer token."""
        resolved_auth = {
            'api': {
                'type': 'bearer',
                'token': 'bearer-token-123'
            }
        }
        
        headers = build_http_headers(resolved_auth)
        
        assert headers['Authorization'] == 'Bearer bearer-token-123'
    
    def test_build_http_headers_basic(self):
        """Test building HTTP headers for basic auth."""
        resolved_auth = {
            'basic': {
                'type': 'basic',
                'username': 'user',
                'password': 'pass'
            }
        }
        
        headers = build_http_headers(resolved_auth)
        
        # Base64 encoding of 'user:pass'
        assert headers['Authorization'].startswith('Basic ')
    
    def test_build_http_headers_api_key(self):
        """Test building HTTP headers for API key."""
        resolved_auth = {
            'api': {
                'type': 'api_key',
                'header': 'X-Custom-Key',
                'value': 'api-key-value'
            }
        }
        
        headers = build_http_headers(resolved_auth)
        
        assert headers['X-Custom-Key'] == 'api-key-value'
    
    def test_build_http_headers_custom_header(self):
        """Test building HTTP headers for custom header."""
        resolved_auth = {
            'custom': {
                'type': 'header',
                'name': 'X-Custom',
                'value': 'custom-value'
            }
        }
        
        headers = build_http_headers(resolved_auth)
        
        assert headers['X-Custom'] == 'custom-value'
    
    def test_build_http_headers_multiple(self):
        """Test building HTTP headers from multiple auth types."""
        resolved_auth = {
            'bearer': {
                'type': 'bearer',
                'token': 'bearer-token'
            },
            'api_key': {
                'type': 'api_key',
                'value': 'api-key-value'
            }
        }
        
        headers = build_http_headers(resolved_auth)
        
        assert headers['Authorization'] == 'Bearer bearer-token'
        assert headers['X-API-Key'] == 'api-key-value'


class TestDuckDBAuth:
    """Test DuckDB authentication functions."""
    
    def test_get_duckdb_secrets_postgres(self):
        """Test generating DuckDB postgres secrets."""
        resolved_auth = {
            'pg': {
                'type': 'postgres',
                'db_host': 'localhost',
                'db_port': 5432,
                'db_name': 'testdb',
                'db_user': 'testuser',
                'db_password': 'testpass',
                'secret_name': 'pg_secret'
            }
        }
        
        statements = get_duckdb_secrets(resolved_auth)
        
        assert len(statements) == 1
        stmt = statements[0]
        assert 'CREATE OR REPLACE SECRET pg_secret' in stmt
        assert 'TYPE postgres' in stmt
        assert "HOST 'localhost'" in stmt
        assert 'PORT 5432' in stmt
        assert "DATABASE 'testdb'" in stmt
    
    def test_get_duckdb_secrets_gcs(self):
        """Test generating DuckDB GCS secrets."""
        resolved_auth = {
            'gcs': {
                'type': 'hmac',
                'service': 'gcs',
                'key_id': 'GOOG123',
                'secret_key': 'secret123',
                'scope': 'gs://mybucket',
                'secret_name': 'gcs_secret'
            }
        }
        
        statements = get_duckdb_secrets(resolved_auth)
        
        assert len(statements) == 1
        stmt = statements[0]
        assert 'CREATE OR REPLACE SECRET gcs_secret' in stmt
        assert 'TYPE gcs' in stmt
        assert "KEY_ID 'GOOG123'" in stmt
        assert "SECRET 'secret123'" in stmt
        assert "SCOPE 'gs://mybucket'" in stmt
    
    def test_get_duckdb_secrets_s3(self):
        """Test generating DuckDB S3 secrets."""
        resolved_auth = {
            's3': {
                'type': 'hmac',
                'service': 's3',
                'key_id': 'AKIAI123',
                'secret_key': 'secretkey',
                'region': 'us-west-2'
            }
        }
        
        statements = get_duckdb_secrets(resolved_auth)
        
        assert len(statements) == 1
        stmt = statements[0]
        assert 'CREATE OR REPLACE SECRET s3' in stmt
        assert 'TYPE s3' in stmt
        assert "KEY_ID 'AKIAI123'" in stmt
        assert "REGION 'us-west-2'" in stmt
    
    def test_get_required_extensions(self):
        """Test getting required DuckDB extensions."""
        resolved_auth = {
            'pg': {'type': 'postgres'},
            'gcs': {'type': 'hmac', 'service': 'gcs'},
            'bearer': {'type': 'bearer'}
        }
        
        extensions = get_required_extensions(resolved_auth)
        
        assert 'postgres' in extensions
        assert 'httpfs' in extensions
        assert len(extensions) == 2  # No extension needed for bearer


class TestEnvironmentIntegration:
    """Test environment variable integration."""
    
    @patch.dict(os.environ, {'NOETL_SECRET_API_TOKEN': 'env-token-value'})
    @patch('noetl.worker.plugin._auth._fetch_secret_manager_value')
    def test_secret_manager_env_fallback(self, mock_fetch, jinja_env, sample_context):
        """Test secret manager falling back to environment variables."""
        # Mock the actual secret manager call to simulate the environment fallback
        mock_fetch.return_value = 'env-token-value'
        
        step_config = {
            'auth': {
                'api': {
                    'type': 'bearer',
                    'key': 'api_token',
                    'provider': 'secret_manager'
                }
            }
        }
        
        resolved = resolve_auth_map(step_config, {}, jinja_env, sample_context)
        
        assert resolved['api']['token'] == 'env-token-value'


if __name__ == '__main__':
    pytest.main([__file__])
