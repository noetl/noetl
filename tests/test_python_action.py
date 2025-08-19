from jinja2 import Environment
from noetl.worker.action import python as py_module


def _events():
    evts = []
    def log_event(*args, **kwargs):
        evts.append((args, kwargs))
        return f"evt-{len(evts)}"
    return evts, log_event


def test_python_execute_success():
    env = Environment()
    code = """
result_holder = {}

def main(x=0, y=0):
    return {'sum': x + y}
"""
    cfg = {'task': 'py', 'code': code}
    ctx = {'a': 1}
    task_with = {'x': 2, 'y': 3}
    ev, logger = _events()

    out = py_module.execute_python_task(cfg, ctx, env, task_with, log_event_callback=logger)

    assert out['status'] == 'success'
    assert out['data']['sum'] == 5
    assert any(a[0][0] == 'task_complete' for a in ev)


def test_python_execute_no_main():
    env = Environment()
    cfg = {'task': 'py', 'code': 'x = 1'}
    out = py_module.execute_python_task(cfg, {}, env, {}, log_event_callback=None)
    assert out['status'] == 'error'
    assert 'Main function must be defined' in out['error']
