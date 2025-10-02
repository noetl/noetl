"""
Integration tests for HTTP job with real weather API calls.
"""

import pytest
import os
from jinja2 import Environment, BaseLoader

from noetl.plugin.http import execute_http_task


@pytest.mark.integration
class TestHttpIntegration:
    """Integration tests that make real HTTP calls."""

    def setup_method(self):
        """Setup for each test method."""
        self.jinja_env = Environment(loader=BaseLoader())

    @pytest.mark.skipif(
        os.getenv('NOETL_SKIP_INTEGRATION_TESTS', 'false').lower() == 'true',
        reason="Integration tests disabled"
    )
    def test_real_weather_api_call(self):
        """Test real weather API call with Berlin coordinates."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://api.open-meteo.com/v1/forecast',
            'data': {
                'query': {
                    'latitude': '{{ debug_data.lat }}',
                    'longitude': '{{ debug_data.lon }}',
                    'hourly': 'temperature_2m',
                    'forecast_days': 1
                }
            },
            'timeout': 10
        }
        
        # Berlin coordinates - same as we've been testing
        context = {
            'debug_data': {
                'lat': 52.52,
                'lon': 13.41,
                'name': 'Berlin'
            }
        }
        task_with = {'debug_data': context['debug_data']}

        result = execute_http_task(task_config, context, self.jinja_env, task_with)

        # Verify the API call succeeded
        assert result['status'] == 'success'
        assert result['data']['status_code'] == 200
        
        # Verify the response structure matches Open-Meteo API
        response_data = result['data']['data']
        assert 'latitude' in response_data
        assert 'longitude' in response_data
        assert 'hourly' in response_data
        assert 'temperature_2m' in response_data['hourly']
        assert 'time' in response_data['hourly']
        
        # Verify coordinates match what we sent
        assert abs(response_data['latitude'] - 52.52) < 0.1
        assert abs(response_data['longitude'] - 13.41) < 0.1
        
        # Verify we got temperature data
        temperatures = response_data['hourly']['temperature_2m']
        assert isinstance(temperatures, list)
        assert len(temperatures) == 24  # 24 hours for 1 day
        assert all(isinstance(temp, (int, float)) for temp in temperatures)
        
        print(f"Integration test: Got {len(temperatures)} temperature readings for Berlin")
        print(f"Temperature range: {min(temperatures):.1f}°C to {max(temperatures):.1f}°C")

    @pytest.mark.skipif(
        os.getenv('NOETL_SKIP_INTEGRATION_TESTS', 'false').lower() == 'true',
        reason="Integration tests disabled"
    )
    def test_real_weather_api_invalid_coordinates(self):
        """Test weather API with invalid coordinates."""
        task_config = {
            'method': 'GET',
            'endpoint': 'https://api.open-meteo.com/v1/forecast',
            'data': {
                'query': {
                    'latitude': 'invalid',
                    'longitude': 'invalid',
                    'hourly': 'temperature_2m'
                }
            },
            'timeout': 10
        }
        
        context = {}
        task_with = {}

        result = execute_http_task(task_config, context, self.jinja_env, task_with)

        # Should get an error response
        assert result['status'] == 'error'
        assert result['data']['status_code'] == 400

    @pytest.mark.skipif(
        os.getenv('NOETL_SKIP_INTEGRATION_TESTS', 'false').lower() == 'true',
        reason="Integration tests disabled"
    )
    def test_multiple_cities_real_api(self):
        """Test real API calls for all three cities from our weather loop."""
        cities = [
            {'name': 'London', 'lat': 51.51, 'lon': -0.13},
            {'name': 'Paris', 'lat': 48.85, 'lon': 2.35},
            {'name': 'Berlin', 'lat': 52.52, 'lon': 13.41}
        ]
        
        task_config = {
            'method': 'GET',
            'endpoint': 'https://api.open-meteo.com/v1/forecast',
            'data': {
                'query': {
                    'latitude': '{{ debug_data.lat }}',
                    'longitude': '{{ debug_data.lon }}',
                    'hourly': 'temperature_2m',
                    'forecast_days': 1
                }
            },
            'timeout': 10
        }

        results = []
        for city in cities:
            context = {'debug_data': city}
            task_with = {'debug_data': city}

            result = execute_http_task(task_config, context, self.jinja_env, task_with)
            results.append((city['name'], result))

            # Each city should get a successful response
            assert result['status'] == 'success'
            assert result['data']['status_code'] == 200
            
            response_data = result['data']['data']
            temperatures = response_data['hourly']['temperature_2m']
            max_temp = max(temperatures)
            
            print(f"{city['name']}: Max temperature {max_temp:.1f}°C")

        # Verify we got different temperature data for different cities
        temps_by_city = {name: max(result['data']['data']['hourly']['temperature_2m']) 
                        for name, result in results}
        
        # Cities should have different temperatures (very likely for different locations)
        temp_values = list(temps_by_city.values())
        assert len(set(temp_values)) > 1, f"All cities had same temperature: {temps_by_city}"


if __name__ == '__main__':
    # Run integration tests
    pytest.main([__file__, '-v', '-m', 'integration'])
