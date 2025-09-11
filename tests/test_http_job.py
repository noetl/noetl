"""
Tests for noetl.job.http module with real-world weather API parameters.
"""

import pytest
import json
import os
from unittest.mock import Mock, patch, MagicMock
from jinja2 import Environment, BaseLoader

from noetl.job.http import execute_http_task


class TestHttpJob:
    """Test suite for HTTP job execution with weather API scenarios."""

    def setup_method(self):
        """Setup for each test method."""
        self.jinja_env = Environment(loader=BaseLoader())
        self.mock_log_callback = Mock()

    def test_basic_get_request(self):
        """Test basic GET request functionality."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://httpbin.org/get',
            'params': {'test': 'value'}
        }
        context = {}
        task_with = {}

        with patch('noetl.job.http.httpx.Client') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.is_success = True
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.url = 'https://httpbin.org/get?test=value'
            mock_response.elapsed.total_seconds.return_value = 0.5
            mock_response.json.return_value = {'args': {'test': 'value'}}
            
            mock_client_instance = Mock()
            mock_client_instance.request.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance

            result = execute_http_task(task_config, context, self.jinja_env, task_with)

            assert result['status'] == 'success'
            assert result['data']['status_code'] == 200
            assert result['data']['data'] == {'args': {'test': 'value'}}

    def test_weather_api_template_rendering(self):
        """Test template rendering with weather API parameters."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://api.open-meteo.com/v1/forecast',
            'params': {
                'latitude': '{{ debug_data.lat }}',
                'longitude': '{{ debug_data.lon }}',
                'hourly': 'temperature_2m',
                'forecast_days': 1
            }
        }
        
        # This is the context structure we've been working with
        context = {
            'debug_data': {
                'lat': 52.52,
                'lon': 13.41,
                'name': 'Berlin'
            }
        }
        task_with = {'debug_data': context['debug_data']}

        with patch('noetl.job.http.httpx.Client') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.is_success = True
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.url = 'https://api.open-meteo.com/v1/forecast?latitude=52.52&longitude=13.41&hourly=temperature_2m&forecast_days=1'
            mock_response.elapsed.total_seconds.return_value = 1.2
            mock_response.json.return_value = {
                'latitude': 52.52,
                'longitude': 13.41,
                'hourly': {
                    'time': ['2025-09-05T00:00', '2025-09-05T01:00'],
                    'temperature_2m': [15.2, 14.8]
                }
            }
            
            mock_client_instance = Mock()
            mock_client_instance.request.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance

            result = execute_http_task(task_config, context, self.jinja_env, task_with, self.mock_log_callback)

            # Verify template rendering worked correctly
            mock_client_instance.request.assert_called_once()
            call_args = mock_client_instance.request.call_args[1]
            
            assert call_args['url'] == 'https://api.open-meteo.com/v1/forecast'
            assert call_args['params']['latitude'] == 52.52  # Should be rendered, not the template
            assert call_args['params']['longitude'] == 13.41  # Should be rendered, not the template
            assert call_args['params']['hourly'] == 'temperature_2m'
            assert call_args['params']['forecast_days'] == 1

            assert result['status'] == 'success'
            assert result['data']['status_code'] == 200

    def test_template_rendering_failure_detection(self):
        """Test detection of template rendering failures (the bug we fixed)."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://api.open-meteo.com/v1/forecast',
            'params': {
                'latitude': '{{ missing_data.lat }}',  # This should cause template error
                'longitude': '{{ missing_data.lon }}',
                'hourly': 'temperature_2m'
            }
        }
        
        context = {}  # Empty context - templates won't render
        task_with = {}

        with patch('noetl.job.http.httpx.Client') as mock_client:
            # The HTTP module should handle template rendering errors gracefully
            # and pass the unrendered templates to the HTTP client
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.is_success = False
            mock_response.reason_phrase = 'Bad Request'
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.url = 'https://api.open-meteo.com/v1/forecast'
            mock_response.elapsed.total_seconds.return_value = 0.3
            mock_response.text = 'Cannot initialize Float from invalid String value {{ missing_data.lat }}'
            
            mock_client_instance = Mock()
            mock_client_instance.request.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance

            result = execute_http_task(task_config, context, self.jinja_env, task_with)

            # Should still make the request but with unrendered templates
            mock_client_instance.request.assert_called_once()
            call_args = mock_client_instance.request.call_args[1]
            
            # These should contain the literal template strings since rendering failed
            assert '{{ missing_data.lat }}' in str(call_args['params']['latitude'])
            assert '{{ missing_data.lon }}' in str(call_args['params']['longitude'])

            assert result['status'] == 'error'
            assert result['data']['status_code'] == 400

    def test_multiple_cities_context(self):
        """Test with multiple city contexts like our weather loop."""
        cities = [
            {'name': 'London', 'lat': 51.51, 'lon': -0.13},
            {'name': 'Paris', 'lat': 48.85, 'lon': 2.35},
            {'name': 'Berlin', 'lat': 52.52, 'lon': 13.41}
        ]
        
        task_config = {
            'method': 'GET',
            'endpoint': 'https://api.open-meteo.com/v1/forecast',
            'params': {
                'latitude': '{{ debug_data.lat }}',
                'longitude': '{{ debug_data.lon }}',
                'hourly': 'temperature_2m',
                'forecast_days': 1
            }
        }

        for city in cities:
            context = {'debug_data': city}
            task_with = {'debug_data': city}

            with patch('noetl.job.http.httpx.Client') as mock_client:
                mock_response = Mock()
                mock_response.status_code = 200
                mock_response.is_success = True
                mock_response.headers = {'Content-Type': 'application/json'}
                mock_response.url = f'https://api.open-meteo.com/v1/forecast?latitude={city["lat"]}&longitude={city["lon"]}'
                mock_response.elapsed.total_seconds.return_value = 1.0
                mock_response.json.return_value = {
                    'latitude': city['lat'],
                    'longitude': city['lon'],
                    'hourly': {
                        'time': ['2025-09-05T12:00'],
                        'temperature_2m': [20.0 + hash(city['name']) % 10]  # Different temp per city
                    }
                }
                
                mock_client_instance = Mock()
                mock_client_instance.request.return_value = mock_response
                mock_client.return_value.__enter__.return_value = mock_client_instance

                result = execute_http_task(task_config, context, self.jinja_env, task_with)

                # Verify each city gets correct coordinates
                call_args = mock_client_instance.request.call_args[1]
                assert call_args['params']['latitude'] == city['lat']
                assert call_args['params']['longitude'] == city['lon']
                assert result['status'] == 'success'

    def test_local_domain_mocking(self):
        """Test local domain mocking functionality."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://test.local/api',
            'params': {'test': 'value'}
        }
        context = {}
        task_with = {}

        # Test with mocking enabled (default for debug)
        with patch.dict(os.environ, {'NOETL_DEBUG': 'true'}):
            result = execute_http_task(task_config, context, self.jinja_env, task_with)
            
            assert result['status'] == 'success'
            assert result['data']['data']['mocked'] is True
            assert result['data']['data']['endpoint'] == 'https://test.local/api'

    def test_post_request_with_json_payload(self):
        """Test POST request with JSON payload."""
        task_config = {
            'method': 'POST',
            'endpoint': 'https://httpbin.org/post',
            'headers': {'Content-Type': 'application/json'},
            'payload': {'city': '{{ city_name }}', 'data': '{{ city_data }}'}
        }
        context = {
            'city_name': 'Berlin',
            'city_data': {'lat': 52.52, 'lon': 13.41}
        }
        task_with = context

        with patch('noetl.job.http.httpx.Client') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.is_success = True
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.url = 'https://httpbin.org/post'
            mock_response.elapsed.total_seconds.return_value = 0.8
            mock_response.json.return_value = {'json': {'city': 'Berlin', 'data': {'lat': 52.52, 'lon': 13.41}}}
            
            mock_client_instance = Mock()
            mock_client_instance.request.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance

            result = execute_http_task(task_config, context, self.jinja_env, task_with)

            # Verify JSON payload was rendered and sent correctly
            call_args = mock_client_instance.request.call_args[1]
            assert 'json' in call_args
            assert call_args['json']['city'] == 'Berlin'
            assert call_args['json']['data'] == {'lat': 52.52, 'lon': 13.41}

    def test_error_handling_http_failure(self):
        """Test error handling for HTTP failures."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://api.open-meteo.com/v1/forecast',
            'params': {'latitude': 'invalid', 'longitude': 'invalid'}
        }
        context = {}
        task_with = {}

        with patch('noetl.job.http.httpx.Client') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 400
            mock_response.is_success = False
            mock_response.reason_phrase = 'Bad Request'
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.url = 'https://api.open-meteo.com/v1/forecast?latitude=invalid&longitude=invalid'
            mock_response.elapsed.total_seconds.return_value = 0.2
            mock_response.text = 'Invalid coordinates'
            
            mock_client_instance = Mock()
            mock_client_instance.request.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance

            result = execute_http_task(task_config, context, self.jinja_env, task_with, self.mock_log_callback)

            assert result['status'] == 'error'
            assert result['data']['status_code'] == 400
            assert 'HTTP 400: Bad Request' in result['error']

    def test_event_logging(self):
        """Test that event logging callbacks are called correctly."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://httpbin.org/get'
        }
        context = {}
        task_with = {}

        with patch('noetl.job.http.httpx.Client') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.is_success = True
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.url = 'https://httpbin.org/get'
            mock_response.elapsed.total_seconds.return_value = 0.5
            mock_response.json.return_value = {'success': True}
            
            mock_client_instance = Mock()
            mock_client_instance.request.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance

            result = execute_http_task(task_config, context, self.jinja_env, task_with, self.mock_log_callback)

            # Should have called log callback twice: task_start and task_complete
            assert self.mock_log_callback.call_count == 2
            
            # Check task_start call
            start_call = self.mock_log_callback.call_args_list[0]
            assert start_call[0][0] == 'task_start'  # event_type
            assert start_call[0][3] == 'http'  # task_type
            assert start_call[0][4] == 'in_progress'  # status
            
            # Check task_complete call
            complete_call = self.mock_log_callback.call_args_list[1]
            assert complete_call[0][0] == 'task_complete'  # event_type
            assert complete_call[0][3] == 'http'  # task_type
            assert complete_call[0][4] == 'success'  # status

    def test_timeout_configuration(self):
        """Test timeout configuration."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://httpbin.org/delay/10',
            'timeout': 5
        }
        context = {}
        task_with = {}

        with patch('noetl.job.http.httpx.Client') as mock_client_class:
            # Verify timeout is passed to client
            result = execute_http_task(task_config, context, self.jinja_env, task_with)
            mock_client_class.assert_called_once_with(timeout=5)

    def test_headers_rendering(self):
        """Test that headers are rendered with templates."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://httpbin.org/headers',
            'headers': {
                'Authorization': 'Bearer {{ api_token }}',
                'X-City': '{{ city_name }}'
            }
        }
        context = {
            'api_token': 'secret123',
            'city_name': 'Berlin'
        }
        task_with = context

        with patch('noetl.job.http.httpx.Client') as mock_client:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.is_success = True
            mock_response.headers = {'Content-Type': 'application/json'}
            mock_response.url = 'https://httpbin.org/headers'
            mock_response.elapsed.total_seconds.return_value = 0.3
            mock_response.json.return_value = {'headers': {'Authorization': 'Bearer secret123', 'X-City': 'Berlin'}}
            
            mock_client_instance = Mock()
            mock_client_instance.request.return_value = mock_response
            mock_client.return_value.__enter__.return_value = mock_client_instance

            result = execute_http_task(task_config, context, self.jinja_env, task_with)

            # Verify headers were rendered correctly
            call_args = mock_client_instance.request.call_args[1]
            assert call_args['headers']['Authorization'] == 'Bearer secret123'
            assert call_args['headers']['X-City'] == 'Berlin'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
