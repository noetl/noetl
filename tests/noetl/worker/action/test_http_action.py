from jinja2 import Environment

from noetl.worker.action import http as http_module


def _event_collector():
    events = []
    def log_event(*args, **kwargs):
        events.append((args, kwargs))
        return f"evt-{len(events)}"
    return events, log_event


def test_http_execute_success(monkeypatch):
    class Resp:
        def __init__(self, status_code=200, data=None):
            self.status_code = status_code
            self._data = data or {'ok': True}
            self.headers = {'Content-Type': 'application/json'}
            self.elapsed = type('E', (), {'total_seconds': lambda self: 0.01})()
            self.url = 'http://example/api'
            self.text = '{}'
        def raise_for_status(self):
            if not (200 <= self.status_code < 300):
                raise Exception(f"status {self.status_code}")
        def json(self):
            return self._data

    class FakeClient:
        def __init__(self, timeout=None, **kwargs):
            self.timeout = timeout
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
                return False
        def request(self, method, url, headers=None, params=None, json=None):
            self.captured = {'method': method, 'url': url, 'headers': headers, 'params': params, 'json': json}
            return Resp()

    monkeypatch.setattr(http_module.httpx, 'Client', FakeClient)

    env = Environment()
    context = {'env': {'NOETL_BASE_URL': 'http://example'}}
    cfg = {'method': 'GET', 'endpoint': '/api', 'timeout': 5}
    events, logger = _event_collector()

    out = http_module.execute_http_task(cfg, context, env, {}, log_event_callback=logger)

    assert out['status'] == 'success'
    assert out['data']['ok'] is True
    assert 'task_complete' in [a[0][0] for a in events]


def test_http_execute_error_status(monkeypatch):
    class Resp:
        def __init__(self):
            self.status_code = 400
            self.headers = {'Content-Type': 'application/json'}
            self.text = 'bad'
        def raise_for_status(self):
            raise Exception('400')
        def json(self):
            return {'err': True}

    class FakeClient:
        def __init__(self, timeout=None, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def request(self, method, url, headers=None, params=None, json=None):
            return Resp()

    monkeypatch.setattr(http_module.httpx, 'Client', FakeClient)

    env = Environment()
    context = {'env': {'NOETL_BASE_URL': 'http://example'}}
    cfg = {'method': 'GET', 'endpoint': '/api'}

    out = http_module.execute_http_task(cfg, context, env, {}, log_event_callback=None)
    assert out['status'] == 'error'
