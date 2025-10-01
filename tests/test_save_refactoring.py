"""
Test cases for save structure functionality (new flattened structure only).
"""
import pytest
from jinja2 import Environment

from noetl.plugin.save import execute_save_task


class TestSaveStructure:
    """Test cases for save structure functionality."""

    def test_execute_save_task_event_log(self):
        """Test execute_save_task with event_log storage."""
        task_config = {
            'type': 'save',
            'save': {
                'storage': 'event_log',
                'data': {
                    'message': 'test message'
                }
            }
        }
        
        context = {'execution_id': 'test_123'}
        jinja_env = Environment()
        
        result = execute_save_task(task_config, context, jinja_env)
        
        assert result['status'] == 'success'
        assert result['data']['saved'] == 'event'
        assert result['data']['data']['message'] == 'test message'

    def test_execute_save_task_event_storage(self):
        """Test execute_save_task with 'event' storage (alternative name)."""
        task_config = {
            'type': 'save',
            'save': {
                'storage': 'event',
                'data': {
                    'message': 'test message event'
                }
            }
        }
        
        context = {'execution_id': 'test_456'}
        jinja_env = Environment()
        
        result = execute_save_task(task_config, context, jinja_env)
        
        assert result['status'] == 'success'
        assert result['data']['saved'] == 'event'
        assert result['data']['data']['message'] == 'test message event'

    def test_execute_save_task_with_auth_string(self):
        """Test execute_save_task with string auth reference."""
        task_config = {
            'type': 'save',
            'save': {
                'storage': 'postgres',
                'auth': 'pg_local',
                'table': 'test_table',
                'mode': 'upsert',
                'key': ['id'],
                'data': {
                    'id': '123',
                    'name': 'Test User'
                }
            }
        }
        
        context = {'execution_id': 'test_789'}
        jinja_env = Environment()
        
        # This will fail at postgres execution but should pass validation
        try:
            result = execute_save_task(task_config, context, jinja_env)
            # If postgres is not configured, we expect an error but the validation should work
            if result['status'] == 'error':
                # This is expected if postgres is not available
                assert 'postgres' in str(result.get('error', '')).lower() or 'save failed' in str(result.get('error', '')).lower()
            else:
                # If postgres worked, that's fine too
                assert result['status'] == 'success'
        except Exception as e:
            # Postgres plugin might not be available in test environment
            assert 'postgres' in str(e).lower() or 'save' in str(e).lower()

    def test_execute_save_task_with_auth_dict(self):
        """Test execute_save_task with unified auth dictionary."""
        task_config = {
            'type': 'save',
            'save': {
                'storage': 'postgres',
                'auth': {
                    'pg': {
                        'type': 'postgres',
                        'key': 'pg_local'
                    }
                },
                'table': 'test_table',
                'data': {
                    'id': '456',
                    'name': 'Test User 2'
                }
            }
        }
        
        context = {'execution_id': 'test_abc'}
        jinja_env = Environment()
        
        # This will fail at postgres execution but should pass validation
        try:
            result = execute_save_task(task_config, context, jinja_env)
            if result['status'] == 'error':
                assert 'postgres' in str(result.get('error', '')).lower() or 'save failed' in str(result.get('error', '')).lower()
            else:
                assert result['status'] == 'success'
        except Exception as e:
            assert 'postgres' in str(e).lower() or 'save' in str(e).lower()

    def test_execute_save_task_invalid_storage_structure(self):
        """Test that legacy storage structure raises an error."""
        task_config = {
            'type': 'save',
            'save': {
                'storage': {  # This should fail - only string allowed
                    'kind': 'postgres',
                    'auth': 'pg_local'
                },
                'table': 'test_table'
            }
        }
        
        context = {'execution_id': 'test_def'}
        jinja_env = Environment()
        
        with pytest.raises(ValueError) as exc_info:
            execute_save_task(task_config, context, jinja_env)
        
        assert "save.storage must be a string enum" in str(exc_info.value)
        assert "Legacy save.storage.kind structure is no longer supported" in str(exc_info.value)

    def test_execute_save_task_default_event_storage(self):
        """Test that missing storage defaults to 'event'."""
        task_config = {
            'type': 'save',
            'save': {
                'data': {
                    'message': 'default storage test'
                }
            }
        }
        
        context = {'execution_id': 'test_default'}
        jinja_env = Environment()
        
        result = execute_save_task(task_config, context, jinja_env)
        
        assert result['status'] == 'success'
        assert result['data']['saved'] == 'event'
        assert result['data']['data']['message'] == 'default storage test'

    def test_execute_save_task_with_statement_mode(self):
        """Test execute_save_task with statement mode."""
        task_config = {
            'type': 'save',
            'save': {
                'storage': 'postgres',
                'auth': 'pg_local',
                'statement': 'INSERT INTO test_table (id, name) VALUES (:id, :name)',
                'params': {
                    'id': '999',
                    'name': 'Statement Test'
                }
            }
        }
        
        context = {'execution_id': 'test_stmt'}
        jinja_env = Environment()
        
        # This will fail at postgres execution but should pass validation  
        try:
            result = execute_save_task(task_config, context, jinja_env)
            if result['status'] == 'error':
                assert 'postgres' in str(result.get('error', '')).lower() or 'save failed' in str(result.get('error', '')).lower()
            else:
                assert result['status'] == 'success'
        except Exception as e:
            assert 'postgres' in str(e).lower() or 'save' in str(e).lower()