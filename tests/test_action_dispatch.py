import pytest
pytest.skip("Moved to tests/noetl/worker/action/", allow_module_level=True)

from jinja2 import Environment

from noetl.worker.action import action as action_module


class DummySecretManager:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_secret(self, task_config, context, log_event_wrapper):
        # exercise the wrapper
        log_event_wrapper('task_start', 'id', task_config.get('task','t'), 'secrets', 'in_progress', 0, context, None, {}, None)
        self.calls.append((task_config, context))
        return self.payload


def _event_collector():
    events = []

    def log_event(event_type, task_id, task_name, node_type, status, duration, context, output_result, metadata, parent_event_id):
        events.append({
            'event_type': event_type,
            'task_id': task_id,
            'task_name': task_name,
            'node_type': node_type,
            'status': status,
            'metadata': metadata or {}
        })
        return f"evt-{len(events)}"

    return events, log_event


def test_execute_task_dispatch_and_return(monkeypatch):
    # Arrange: fake underlying http action
    called = {}

    def fake_http(task_config, context, jinja_env, task_with, log_event_callback=None):
        called['params'] = {'task_config': task_config, 'context': dict(context), 'task_with': dict(task_with)}
        return {'id': 'x', 'status': 'success', 'data': {'value': 42}}

    monkeypatch.setattr(action_module._http, 'execute_http_task', fake_http)

    env = Environment()
    context = {'foo': 'bar'}
    task_config = {
        'type': 'http',
        'with': {'x': 1},
        'return': '{{ result.value }}'
    }
    events, logger = _event_collector()

    # Act
    res = action_module.execute_task(task_config, 'my_task', context, env, secret_manager=None, log_event_callback=logger)

    # Assert
    assert res['status'] == 'success'
    assert res['data'] == 42
    # ensure context was enriched with task_with for dispatch
    assert called['params']['context']['x'] == 1
    # ensure event logged
    assert any(e['event_type'] == 'task_execute' for e in events)


def test_execute_task_unsupported_type(monkeypatch):
    env = Environment()
    events, logger = _event_collector()

    res = action_module.execute_task({'type': 'unknown'}, 'bad_task', {}, env, secret_manager=None, log_event_callback=logger)

    assert res['status'] == 'error'
    assert 'Unsupported task type' in res['error']
    assert any(e['event_type'] == 'task_error' for e in events)


def test_execute_task_missing_task(monkeypatch):
    env = Environment()
    events, logger = _event_collector()

    # Use empty dict (falsy) instead of None to avoid type warnings while hitting the same code path
    res = action_module.execute_task({}, 'missing', {}, env, secret_manager=None, log_event_callback=logger)

    assert res['status'] == 'error'
    assert 'Task not found' in res['error']


def test_execute_task_secrets(monkeypatch):
    env = Environment()
    events, logger = _event_collector()
    sm = DummySecretManager({'id': 'sec-1', 'status': 'success', 'data': {'k':'v'}})

    res = action_module.execute_task({'type': 'secrets', 'task': 'secret_task'}, 'secret_task', {'a':1}, env, secret_manager=sm, log_event_callback=logger)

    assert res == sm.payload
    assert sm.calls, 'SecretManager.get_secret should be called'


def test_report_event_success(monkeypatch):
    # Fake httpx client
    class Resp:
        def __init__(self):
            self._json = {'ok': True}
        def raise_for_status(self):
            return None
        def json(self):
            return self._json

    class FakeClient:
        def __init__(self, timeout=None):
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def post(self, url, json=None):
            self.captured = (url, json)
            return Resp()

    monkeypatch.setattr(action_module.httpx, 'Client', FakeClient)

    payload = {'event': 'x'}
    out = action_module.report_event(payload, 'http://server')
    assert out['ok'] is True


def test_report_event_failure(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def post(self, url, json=None):
            raise RuntimeError('boom')

    monkeypatch.setattr(action_module.httpx, 'Client', FakeClient)
    # reset failure counter
    if hasattr(action_module.report_event, 'failure_count'):
        delattr(action_module.report_event, 'failure_count')

    out = action_module.report_event({'e':1}, 'http://server')
    assert out['status'] == 'error'
