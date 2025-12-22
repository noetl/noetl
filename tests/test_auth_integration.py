"""
Integration tests for NoETL plugin authentication systems.

Tests the complete authentication flow from configuration through resolution
to plugin execution, ensuring proper integration between auth resolver,
validation, and plugin implementations.
"""

import pytest
from unittest.mock import patch, MagicMock
from jinja2 import Environment

from noetl.tools.postgres import execute_postgres_task
from noetl.tools.http import execute_http_task
from noetl.tools.duckdb import execute_duckdb_task


class TestPluginAuthIntegration:
    """Test suite for plugin authentication integration."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.jinja_env = Environment()
        self.context = {"execution_id": "test-integration-123"}
        self.log_callback = MagicMock()
    
    @patch('noetl.tools.postgres.psycopg.connect')
    @patch('noetl.worker.auth_resolver.fetch_credential_by_key')
    def test_postgres_unified_auth_integration(self, mock_fetch_cred, mock_connect):
        """Test Postgres plugin with unified auth system."""
        # Mock credential fetch
        mock_fetch_cred.return_value = {
            "host": "test-postgres.example.com",
            "port": 5432,
            "user": "testuser",
            "password": "testpass",
            "database": "testdb"
        }
        
        # Mock database connection
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value.__enter__.return_value = mock_cursor
        mock_cursor.description = [["id"], ["name"], ["created_at"]]
        mock_cursor.fetchall.return_value = [
            (1, "Test Record", "2023-01-01T00:00:00Z")
        ]
        mock_connect.return_value = mock_conn
        
        task_config = {
            "task": "test_postgres_task",
            "type": "postgres",
            "auth": {
                "type": "postgres",
                "credential": "pg_test"
            },
            "command_b64": "U0VMRUNUIGlkLCBuYW1lLCBjcmVhdGVkX2F0IEZST00gdGVzdF90YWJsZTs="  # SELECT id, name, created_at FROM test_table;
        }
        
        task_with = {}
        
        result = execute_postgres_task(
            task_config, self.context, self.jinja_env, task_with, self.log_callback
        )
        
        assert result["status"] == "success"
        assert "data" in result
        mock_fetch_cred.assert_called_once_with("pg_test")
        mock_connect.assert_called_once()
    
    @patch('noetl.tools.postgres.psycopg.connect')
    def test_postgres_inline_auth_integration(self, mock_connect):
        """Test Postgres plugin with inline auth configuration."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        
        task_config = {
            "task": "test_postgres_task",
            "type": "postgres",
            "auth": {
                "type": "postgres",
                "inline": {
                    "host": "localhost",
                    "port": 5432,
                    "user": "admin",
                    "password": "admin123",
                    "database": "integration_test"
                }
            },
            "command_b64": "U0VMRUNUIDEgYXMgdGVzdF9jb2w7"  # SELECT 1 as test_col;
        }
        
        task_with = {}
        
        result = execute_postgres_task(
            task_config, self.context, self.jinja_env, task_with, self.log_callback
        )
        
        assert result["status"] == "success"
        # Verify connection was made with inline credentials
        call_args = mock_connect.call_args[0][0]
        assert "host=localhost" in call_args
        assert "user=admin" in call_args
        assert "dbname=integration_test" in call_args
    
    @patch('httpx.Client')
    def test_http_bearer_auth_integration(self, mock_httpx_client):
        """Test HTTP plugin with Bearer token authentication."""
        # Mock HTTP client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"result": "success", "data": "test"}
        mock_response.url = "https://api.example.com/test"
        mock_response.elapsed.total_seconds.return_value = 0.5
        
        mock_client.request.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        
        task_config = {
            "task": "test_http_task",
            "type": "http",
            "method": "GET",
            "endpoint": "https://api.example.com/test",
            "auth": {
                "type": "bearer",
                "inline": {
                    "token": "test-bearer-token-123"
                }
            }
        }
        
        task_with = {}
        
        result = execute_http_task(
            task_config, self.context, self.jinja_env, task_with, self.log_callback
        )
        
        assert result["status"] == "success"
        assert result["data"]["status_code"] == 200
        
        # Verify Bearer token was added to headers
        request_call = mock_client.request.call_args
        headers = request_call[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer test-bearer-token-123"
    
    @patch('httpx.Client')
    def test_http_basic_auth_integration(self, mock_httpx_client):
        """Test HTTP plugin with Basic authentication."""
        # Mock HTTP client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.text = "Success"
        mock_response.url = "https://api.example.com/basic"
        mock_response.elapsed.total_seconds.return_value = 0.3
        
        mock_client.request.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        
        task_config = {
            "task": "test_http_basic_task",
            "type": "http",
            "method": "POST",
            "endpoint": "https://api.example.com/basic",
            "auth": {
                "type": "basic",
                "inline": {
                    "username": "testuser",
                    "password": "testpass"
                }
            }
        }
        
        task_with = {}
        
        result = execute_http_task(
            task_config, self.context, self.jinja_env, task_with, self.log_callback
        )
        
        assert result["status"] == "success"
        
        # Verify Basic auth header was added
        request_call = mock_client.request.call_args
        headers = request_call[1]["headers"]
        assert "Authorization" in headers
        assert headers["Authorization"].startswith("Basic ")
    
    @patch('httpx.Client')
    def test_http_api_key_auth_integration(self, mock_httpx_client):
        """Test HTTP plugin with API key authentication."""
        # Mock HTTP client
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.text = "API key accepted"
        mock_response.url = "https://api.example.com/apikey"
        mock_response.elapsed.total_seconds.return_value = 0.2
        
        mock_client.request.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        
        task_config = {
            "task": "test_http_apikey_task",
            "type": "http",
            "method": "GET",
            "endpoint": "https://api.example.com/apikey",
            "auth": {
                "type": "api_key",
                "inline": {
                    "key": "X-API-Key",
                    "value": "secret-api-key-value"
                }
            }
        }
        
        task_with = {}
        
        result = execute_http_task(
            task_config, self.context, self.jinja_env, task_with, self.log_callback
        )
        
        assert result["status"] == "success"
        
        # Verify API key header was added
        request_call = mock_client.request.call_args
        headers = request_call[1]["headers"]
        assert "X-API-Key" in headers
        assert headers["X-API-Key"] == "secret-api-key-value"
    
    @patch('duckdb.connect')
    @patch('noetl.worker.auth_resolver.fetch_credential_by_key')
    def test_duckdb_multi_auth_integration(self, mock_fetch_cred, mock_duckdb_connect):
        """Test DuckDB plugin with multi-auth configuration."""
        # Mock credential fetches
        def mock_fetch_side_effect(key):
            if key == "pg_main":
                return {
                    "host": "postgres.example.com",
                    "port": 5432,
                    "user": "dbuser",
                    "password": "dbpass",
                    "database": "maindb"
                }
            elif key == "gcs_hmac":
                return {
                    "key_id": "HMAC_KEY_ID_123",
                    "secret_key": "HMAC_SECRET_KEY_456"
                }
            return {}
        
        mock_fetch_cred.side_effect = mock_fetch_side_effect
        
        # Mock DuckDB connection
        mock_conn = MagicMock()
        mock_duckdb_connect.return_value = mock_conn
        
        task_config = {
            "task": "test_duckdb_task",
            "type": "duckdb",
            "auth": {
                "db": {
                    "type": "postgres",
                    "credential": "pg_main"
                },
                "storage": {
                    "type": "gcs",
                    "credential": "gcs_hmac"
                }
            },
            "command_b64": "U0VMRUNUIDEgYXMgdGVzdDsgLS0gU2ltcGxlIHRlc3QgcXVlcnk="  # SELECT 1 as test; -- Simple test query
        }
        
        task_with = {"auto_secrets": True}
        
        result = execute_duckdb_task(
            task_config, self.context, self.jinja_env, task_with, self.log_callback
        )
        
        assert result["status"] == "success"
        
        # Verify credential fetches were called
        assert mock_fetch_cred.call_count >= 2
        mock_fetch_cred.assert_any_call("pg_main")
        mock_fetch_cred.assert_any_call("gcs_hmac")
        
        # Verify DuckDB connection was established
        mock_duckdb_connect.assert_called()
        
        # Verify that CREATE SECRET statements were executed
        executed_statements = [call[0][0] for call in mock_conn.execute.call_args_list]
        create_secret_statements = [stmt for stmt in executed_statements if "CREATE OR REPLACE SECRET" in stmt]
        assert len(create_secret_statements) >= 2  # Should have postgres and gcs secrets
    
    @patch('duckdb.connect')
    def test_duckdb_single_auth_auto_wrap(self, mock_duckdb_connect):
        """Test DuckDB plugin auto-wrapping single auth to multi-auth."""
        # Mock DuckDB connection
        mock_conn = MagicMock()
        mock_duckdb_connect.return_value = mock_conn
        
        task_config = {
            "task": "test_duckdb_single_task",
            "type": "duckdb",
            "auth": {
                "type": "postgres",
                "inline": {
                    "host": "single.example.com",
                    "port": 5432,
                    "user": "singleuser",
                    "password": "singlepass",
                    "database": "singledb"
                }
            },
            "command_b64": "U0VMRUNUICdhdXRvLXdyYXBwZWQnIGFzIG1lc3NhZ2U7"  # SELECT 'auto-wrapped' as message;
        }
        
        task_with = {"auto_secrets": True}
        
        result = execute_duckdb_task(
            task_config, self.context, self.jinja_env, task_with, self.log_callback
        )
        
        assert result["status"] == "success"
        
        # Verify DuckDB connection was established
        mock_duckdb_connect.assert_called()
        
        # Verify that CREATE SECRET statement was executed for auto-wrapped auth
        executed_statements = [call[0][0] for call in mock_conn.execute.call_args_list]
        create_secret_statements = [stmt for stmt in executed_statements if "CREATE OR REPLACE SECRET default" in stmt]
        assert len(create_secret_statements) == 1  # Should have one secret with 'default' alias
    
    @patch('noetl.tools.postgres.psycopg.connect')
    def test_backwards_compatibility_credentials_field(self, mock_connect):
        """Test backwards compatibility with deprecated 'credentials' field."""
        # Mock database connection
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        
        task_config = {
            "task": "test_legacy_postgres_task",
            "type": "postgres", 
            "credentials": "legacy_pg_cred",  # Deprecated field
            "command_b64": "U0VMRUNUICdsZWdhY3knIGFzIHRlc3Q7"  # SELECT 'legacy' as test;
        }
        
        with patch('noetl.worker.auth_resolver.fetch_credential_by_key') as mock_fetch:
            mock_fetch.return_value = {
                "host": "legacy.example.com",
                "port": 5432,
                "user": "legacyuser",
                "password": "legacypass",
                "database": "legacydb"
            }
            
            task_with = {}
            
            with patch('noetl.tools.postgres.logger') as mock_logger:
                result = execute_postgres_task(
                    task_config, self.context, self.jinja_env, task_with, self.log_callback
                )
                
                assert result["status"] == "success"
                
                # Verify deprecation warning was logged
                mock_logger.warning.assert_called()
                warning_calls = mock_logger.warning.call_args_list
                deprecation_warnings = [call for call in warning_calls if "deprecated 'credentials'" in str(call)]
                assert len(deprecation_warnings) > 0
    
    def test_auth_validation_integration(self):
        """Test auth validation integration with plugin configuration."""
        from noetl.worker.auth_validation import validate_step_auth
        
        # Valid configuration should pass
        valid_config = {
            "task": "test_task",
            "type": "postgres",
            "auth": {
                "type": "postgres",
                "credential": "pg_test"
            }
        }
        
        # Should not raise any exceptions
        validate_step_auth(valid_config)
        
        # Invalid configuration should fail
        invalid_config = {
            "task": "test_task",
            "type": "postgres",
            "auth": {
                "type": "postgres"
                # Missing source (credential, inline, etc.)
            }
        }
        
        with pytest.raises(Exception):  # Should raise validation error
            validate_step_auth(invalid_config)
    
    @patch('os.environ.get')
    def test_auth_env_variable_integration(self, mock_env_get):
        """Test auth resolution with environment variables."""
        mock_env_get.return_value = "env-api-token-123"
        
        from noetl.worker.auth_resolver import resolve_auth
        
        auth_config = {
            "type": "bearer",
            "env": "API_TOKEN"
        }
        
        result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
        
        assert result is not None
        assert result.auth_type == "bearer"
        assert result.config["token"] == "env-api-token-123"
        mock_env_get.assert_called_with("API_TOKEN")


if __name__ == "__main__":
    pytest.main([__file__])