"""
Security tests for NoETL auth system.
Test secure handling of credentials, SQL injection prevention, and sanitization.
"""

import pytest
import json
import base64
from unittest.mock import Mock, patch, MagicMock
from jinja2 import Environment
import tempfile
import os
from pathlib import Path

from noetl.tools.postgres import execute_postgres_task
from noetl.tools.http import execute_http_task
from noetl.tools.duckdb import execute_duckdb_task

import pytest
from unittest.mock import patch, MagicMock
import logging
from io import StringIO
from jinja2 import Environment

from noetl.worker.auth_resolver import resolve_auth, ResolvedAuthItem


class TestAuthSecurity:
    """Test suite for authentication security and secret redaction."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.jinja_env = Environment()
        self.context = {"execution_id": "security-test-123"}
        
        # Capture log output for security testing
        self.log_stream = StringIO()
        self.log_handler = logging.StreamHandler(self.log_stream)
        self.log_handler.setLevel(logging.DEBUG)
        
        # Add handler to relevant loggers
        loggers = [
            logging.getLogger("noetl.worker.auth_resolver"),
            logging.getLogger("noetl.tools.postgres"),
            logging.getLogger("noetl.tools.http"),
            logging.getLogger("noetl.tools.duckdb")
        ]
        
        for logger in loggers:
            logger.addHandler(self.log_handler)
            logger.setLevel(logging.DEBUG)
    
    def teardown_method(self):
        """Clean up test fixtures."""
        # Remove log handler
        loggers = [
            logging.getLogger("noetl.worker.auth_resolver"),
            logging.getLogger("noetl.tools.postgres"),
            logging.getLogger("noetl.tools.http"),
            logging.getLogger("noetl.tools.duckdb")
        ]
        
        for logger in loggers:
            logger.removeHandler(self.log_handler)
    
    def test_resolved_auth_item_redaction(self):
        """Test that ResolvedAuthItem properly redacts sensitive fields."""
        sensitive_config = {
            "host": "secure.example.com",
            "user": "admin",
            "password": "super_secret_password_123",
            "token": "bearer_token_xyz_789",
            "secret_key": "hmac_secret_key_456",
            "api_key": "api_key_secret_789",
            "client_secret": "oauth_client_secret_123"
        }
        
        auth_item = ResolvedAuthItem(
            auth_type="postgres",
            config=sensitive_config
        )
        
        # String representation should redact sensitive fields
        str_repr = str(auth_item)
        repr_repr = repr(auth_item)
        
        # Sensitive values should not appear in string representations
        sensitive_values = [
            "super_secret_password_123",
            "bearer_token_xyz_789", 
            "hmac_secret_key_456",
            "api_key_secret_789",
            "oauth_client_secret_123"
        ]
        
        for sensitive_value in sensitive_values:
            assert sensitive_value not in str_repr, f"Sensitive value '{sensitive_value}' found in str() output"
            assert sensitive_value not in repr_repr, f"Sensitive value '{sensitive_value}' found in repr() output"
        
        # Should contain redaction markers
        assert "[REDACTED]" in str_repr
        assert "[REDACTED]" in repr_repr
        
        # Non-sensitive fields should still be visible
        assert "secure.example.com" in str_repr
        assert "admin" in str_repr
    
    def test_auth_resolver_log_redaction(self):
        """Test that auth resolver doesn't log sensitive information."""
        auth_config = {
            "type": "postgres",
            "inline": {
                "host": "db.example.com",
                "user": "admin",
                "password": "secret_database_password_456",
                "database": "production"
            }
        }
        
        # Clear log stream
        self.log_stream.seek(0)
        self.log_stream.truncate(0)
        
        result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
        
        # Get logged content
        log_content = self.log_stream.getvalue()
        
        # Sensitive password should not appear in logs
        assert "secret_database_password_456" not in log_content, "Password found in auth resolver logs"
        
        # Non-sensitive information should be logged (for debugging)
        assert "db.example.com" in log_content or log_content == "", "Host info should be in logs or logs should be minimal"
    
    @patch('noetl.tools.postgres.psycopg.connect')
    def test_postgres_connection_string_redaction(self, mock_connect):
        """Test that Postgres connection strings are redacted in logs."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        
        task_config = {
            "task": "security_test_postgres",
            "type": "postgres",
            "auth": {
                "type": "postgres",
                "inline": {
                    "host": "postgres.example.com",
                    "port": 5432,
                    "user": "secure_user",
                    "password": "ultra_secret_password_789",
                    "database": "secure_db"
                }
            },
            "command_b64": "U0VMRUNUIDEgYXMgc2VjdXJpdHlfdGVzdDs="  # SELECT 1 as security_test;
        }
        
        # Clear log stream
        self.log_stream.seek(0)
        self.log_stream.truncate(0)
        
        task_with = {}
        
        try:
            result = execute_postgres_task(
                task_config, self.context, self.jinja_env, task_with, MagicMock()
            )
        except Exception:
            pass  # We're testing logging, not execution success
        
        # Get logged content
        log_content = self.log_stream.getvalue()
        
        # Password should not appear in logs
        assert "ultra_secret_password_789" not in log_content, "Password found in Postgres plugin logs"
        
        # Connection attempt should be logged with redacted password
        if "Failed to connect to PostgreSQL" in log_content:
            # Connection failure logs should have redacted passwords
            assert "password=***" in log_content or "password=[REDACTED]" in log_content
    
    @patch('httpx.Client')
    def test_http_auth_header_redaction(self, mock_httpx_client):
        """Test that HTTP authentication headers are redacted in logs."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.is_success = True
        mock_response.headers = {}
        mock_response.text = "Success"
        mock_response.url = "https://api.example.com/secure"
        mock_response.elapsed.total_seconds.return_value = 0.1
        
        mock_client.request.return_value = mock_response
        mock_httpx_client.return_value.__enter__.return_value = mock_client
        
        task_config = {
            "task": "security_test_http",
            "type": "http",
            "method": "GET",
            "endpoint": "https://api.example.com/secure",
            "auth": {
                "type": "bearer",
                "inline": {
                    "token": "highly_secret_bearer_token_123"
                }
            }
        }
        
        # Clear log stream
        self.log_stream.seek(0)
        self.log_stream.truncate(0)
        
        task_with = {}
        
        result = execute_http_task(
            task_config, self.context, self.jinja_env, task_with, MagicMock()
        )
        
        # Get logged content
        log_content = self.log_stream.getvalue()
        
        # Bearer token should not appear in logs
        assert "highly_secret_bearer_token_123" not in log_content, "Bearer token found in HTTP plugin logs"
        
        # Should contain redacted header information if debug logging is enabled
        if "[REDACTED]" not in log_content and "redacted" not in log_content.lower():
            # If no explicit redaction logging, then the sensitive header shouldn't be logged at all
            assert "Authorization" not in log_content or "Bearer" not in log_content
    
    @patch('duckdb.connect')
    def test_duckdb_secret_statement_redaction(self, mock_duckdb_connect):
        """Test that DuckDB CREATE SECRET statements are redacted in logs."""
        mock_conn = MagicMock()
        mock_duckdb_connect.return_value = mock_conn
        
        task_config = {
            "task": "security_test_duckdb",
            "type": "duckdb",
            "auth": {
                "storage": {
                    "type": "gcs",
                    "inline": {
                        "key_id": "HMAC_KEY_PUBLIC_PART",
                        "secret_key": "ultra_secret_hmac_key_456"
                    }
                }
            },
            "command_b64": "U0VMRUNUICdzZWN1cml0eV90ZXN0JyBhcyBtZXNzYWdlOw=="  # SELECT 'security_test' as message;
        }
        
        # Clear log stream
        self.log_stream.seek(0)
        self.log_stream.truncate(0)
        
        task_with = {"auto_secrets": True}
        
        result = execute_duckdb_task(
            task_config, self.context, self.jinja_env, task_with, MagicMock()
        )
        
        # Get logged content
        log_content = self.log_stream.getvalue()
        
        # Secret key should not appear in logs
        assert "ultra_secret_hmac_key_456" not in log_content, "Secret key found in DuckDB plugin logs"
        
        # Should contain redacted CREATE SECRET statements
        if "CREATE OR REPLACE SECRET" in log_content:
            assert "[REDACTED]" in log_content, "CREATE SECRET statements should be redacted"
    
    def test_auth_resolver_error_message_redaction(self):
        """Test that error messages don't expose sensitive information."""
        auth_config = {
            "type": "postgres",
            "credential": "nonexistent_key_with_sensitive_name"
        }
        
        with patch('noetl.worker.auth_resolver.fetch_credential_by_key') as mock_fetch:
            mock_fetch.side_effect = Exception("Credential not found: contains_password_secret_123")
            
            try:
                resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
                assert False, "Should have raised an exception"
            except Exception as e:
                error_message = str(e)
                
                # Error should mention the credential key but not expose internal sensitive details
                assert "nonexistent_key_with_sensitive_name" in error_message
                
                # Should not contain sensitive parts from internal error
                assert "contains_password_secret_123" not in error_message
    
    def test_backwards_compatibility_credentials_field_redaction(self):
        """Test that deprecated credentials field handling doesn't log sensitive data."""
        from noetl.worker.auth_compatibility import transform_credentials_to_auth
        
        step_config = {
            "task": "test_task",
            "credentials": {
                "type": "postgres",
                "inline": {
                    "password": "legacy_secret_password_789"
                }
            }
        }
        
        task_with = {}
        
        # Clear log stream  
        self.log_stream.seek(0)
        self.log_stream.truncate(0)
        
        updated_step, updated_with = transform_credentials_to_auth(step_config, task_with)
        
        # Get logged content
        log_content = self.log_stream.getvalue()
        
        # Password should not appear in compatibility layer logs
        assert "legacy_secret_password_789" not in log_content, "Password found in compatibility layer logs"
        
        # Should log deprecation warning but not sensitive data
        if log_content:
            assert "deprecated" in log_content.lower()
    
    def test_jinja_template_rendering_with_secrets(self):
        """Test that Jinja template errors don't expose sensitive template content."""
        auth_config = {
            "type": "postgres",
            "inline": {
                "host": "{{ invalid_template_var }}",
                "password": "template_secret_password_123"
            }
        }
        
        # Clear log stream
        self.log_stream.seek(0) 
        self.log_stream.truncate(0)
        
        try:
            # This should fail due to undefined template variable
            result = resolve_auth(auth_config, self.context, self.jinja_env, mode='single')
        except Exception as e:
            error_message = str(e)
            
            # Error message should not contain the sensitive password from the template
            assert "template_secret_password_123" not in error_message
            
            # Get logged content
            log_content = self.log_stream.getvalue()
            
            # Logs should not contain the sensitive password
            assert "template_secret_password_123" not in log_content
    
    def test_multi_auth_redaction_comprehensive(self):
        """Test comprehensive redaction in multi-auth configurations."""
        multi_auth_map = {
            "db": ResolvedAuthItem("postgres", {
                "host": "db.example.com",
                "password": "db_secret_456"
            }),
            "api": ResolvedAuthItem("bearer", {
                "token": "api_secret_789"
            }),
            "storage": ResolvedAuthItem("gcs", {
                "key_id": "PUBLIC_KEY_ID",
                "secret_key": "storage_secret_123"
            })
        }
        
        # Test string representation of the entire map
        map_str = str(multi_auth_map)
        
        # All sensitive values should be redacted
        sensitive_values = ["db_secret_456", "api_secret_789", "storage_secret_123"]
        
        for sensitive_value in sensitive_values:
            assert sensitive_value not in map_str, f"Sensitive value '{sensitive_value}' found in multi-auth map string"
        
        # Should contain redaction markers
        assert "[REDACTED]" in map_str
        
        # Non-sensitive values should be present
        assert "db.example.com" in map_str
        assert "PUBLIC_KEY_ID" in map_str


if __name__ == "__main__":
    pytest.main([__file__])