import os
from jinja2 import Environment
from noetl.plugin.http import execute_http_task


def test_get_routes_data_to_query(monkeypatch):
    monkeypatch.setenv('NOETL_HTTP_MOCK_LOCAL', 'true')
    jenv = Environment()
    ctx = {'workload': {}, 'execution_id': 'e1'}
    task = {
        'type': 'http',
        'method': 'GET',
        'endpoint': 'http://example.local/echo',
        'data': {'q': 'k', 'page': 2}
    }
    out = execute_http_task(task, ctx, jenv, {}, None)
    assert out['status'] == 'success'
    # Mocked path returns data map under data.data
    assert out['data']['data']['data']['q'] == 'k'


def test_post_routes_data_to_body(monkeypatch):
    monkeypatch.setenv('NOETL_HTTP_MOCK_LOCAL', 'true')
    jenv = Environment()
    ctx = {'workload': {}, 'execution_id': 'e2'}
    task = {
        'type': 'http',
        'method': 'POST',
        'endpoint': 'http://example.local/echo',
        'data': {'name': 'alice', 'age': 5}
    }
    out = execute_http_task(task, ctx, jenv, {}, None)
    assert out['status'] == 'success'
    # Ensure our data is plumbed through mock payload or data field
    payload = out['data']['data'].get('payload') or {}
    # Legacy mock puts payload under 'payload'; if not present, check new 'data' field
    if not payload:
        payload = out['data']['data'].get('data')
    assert payload['name'] == 'alice'

