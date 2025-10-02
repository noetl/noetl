"""
Basic tests for the refactored DuckDB plugin structure.
"""

import pytest
import tempfile
import base64
from unittest.mock import MagicMock
from jinja2 import Environment

from noetl.plugin.duckdb import execute_duckdb_task
from noetl.plugin.duckdb.config import create_task_config, create_connection_config
from noetl.plugin.duckdb.connections import get_duckdb_connection
from noetl.plugin.duckdb.sql import render_commands, clean_sql_text
from noetl.plugin.duckdb.types import ConnectionConfig, TaskConfig


class TestDuckDBRefactoredStructure:
    """Test the refactored DuckDB plugin structure."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.jinja_env = Environment()
        self.context = {"test_var": "test_value"}
        
    def test_task_config_creation(self):
        """Test TaskConfig creation from raw configuration."""
        task_config = {
            "task": "test_task",
            "commands_b64": base64.b64encode("SELECT 1;".encode()).decode()
        }
        task_with = {"auto_secrets": False}
        
        config = create_task_config(task_config, task_with, self.jinja_env, self.context)
        
        assert isinstance(config, TaskConfig)
        assert config.task_name == "test_task"
        assert config.commands == "SELECT 1;"
        assert config.auto_secrets is False
        
    def test_connection_config_creation(self):
        """Test ConnectionConfig creation."""
        task_config = {}
        task_with = {}
        context = {"execution_id": "test-123"}
        
        config = create_connection_config(context, task_config, task_with, self.jinja_env)
        
        assert isinstance(config, ConnectionConfig)
        assert config.execution_id == "test-123"
        assert "duckdb_test-123.duckdb" in config.database_path
        
    def test_sql_rendering(self):
        """Test SQL command rendering."""
        commands = "SELECT '{{ test_var }}' as value; -- Comment line\nSELECT 2;"
        
        rendered = render_commands(commands, self.jinja_env, self.context)
        
        assert len(rendered) == 2
        assert "SELECT 'test_value' as value" in rendered[0]
        assert "SELECT 2" in rendered[1]
        
    def test_sql_cleaning(self):
        """Test SQL text cleaning."""
        sql = """
        SELECT 1;
        
        # Another comment
        SELECT 2;
        -- Final comment
        """
        
        cleaned = clean_sql_text(sql)
        
        assert len(cleaned) == 2
        assert all("SELECT" in cmd for cmd in cleaned)
        # Note: inline comments within statements are handled by sql_split, not clean_sql_text
        
    @pytest.mark.integration
    def test_basic_duckdb_execution(self):
        """Test basic DuckDB task execution without authentication."""
        with tempfile.TemporaryDirectory() as tmpdir:
            task_config = {
                "task": "test_simple",
                "type": "duckdb", 
                "database": f"{tmpdir}/test.duckdb",
                "commands_b64": base64.b64encode("SELECT 1 as result;".encode()).decode()
            }
            
            task_with = {"auto_secrets": False}
            context = {"execution_id": "test-simple"}
            
            def mock_log_callback(event_type, task_id, task_name, plugin_type, status, duration, context, data, metadata, event_id):
                return "event-123"
            
            result = execute_duckdb_task(
                task_config, context, self.jinja_env, task_with, mock_log_callback
            )
            
            assert result["status"] == "success"
            assert "executed_commands" in result["data"]
            assert result["data"]["executed_commands"] == 1
            
    def test_connection_context_manager(self):
        """Test connection context manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config = ConnectionConfig(
                database_path=f"{tmpdir}/test.duckdb",
                execution_id="test"
            )
            
            with get_duckdb_connection(config) as conn:
                # Test that we can execute a simple query
                result = conn.execute("SELECT 1 as test").fetchone()
                assert result[0] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])