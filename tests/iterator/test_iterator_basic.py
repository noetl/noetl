import pytest

from jinja2 import Environment

from noetl.tools import execute_task


def make_python_task(func_body: str):
    return {
        'type': 'python',
        'code': f"""
def main(value=None, batch=None):
    {func_body}
"""
    }


def test_iterator_sequential_basic():
    jenv = Environment()
    ctx = {'workload': {}, 'execution_id': 'test-exec'}
    task = {
        'type': 'iterator',
        'collection': [1, 2, 3],
        'element': 'value',
        'task': make_python_task("return {'value': int(value), 'square': int(value) * int(value)}"),
    }
    res = execute_task(task, 'iter', ctx, jenv, {})
    assert res['status'] == 'success'
    items = res['data']
    assert len(items) == 3
    assert items[0]['square'] == 1
    assert items[2]['square'] == 9


def test_iterator_async_order_preserved():
    jenv = Environment()
    ctx = {'workload': {}, 'execution_id': 'test-exec'}
    # Simulate varied durations by arithmetic, but order must match input indices
    task = {
        'type': 'iterator',
        'collection': [3, 1, 2],
        'element': 'value',
        'mode': 'async',
        'concurrency': 4,
        'task': make_python_task("return {'value': int(value)}"),
    }
    res = execute_task(task, 'iter', ctx, jenv, {})
    assert res['status'] == 'success'
    items = res['data']
    # order preserved as input logical order (3,1,2)
    assert [x['value'] for x in items] == [3, 1, 2]


def test_iterator_where_limit_sort():
    jenv = Environment()
    ctx = {'workload': {}, 'execution_id': 'test-exec'}
    task = {
        'type': 'iterator',
        'collection': [{'x': 3}, {'x': 1}, {'x': 2}, {'x': 0}],
        'element': 'row',
        'where': "{{ row.x > 0 }}",
        'order_by': "{{ row.x }}",
        'limit': 2,
        'task': make_python_task("return {'x': int(value['x'])}"),
    }
    res = execute_task(task, 'iter', ctx, jenv, {})
    assert res['status'] == 'success'
    xs = [x['x'] for x in res['data']]
    assert xs == [1, 2]


def test_iterator_chunking():
    jenv = Environment()
    ctx = {'workload': {}, 'execution_id': 'test-exec'}
    # Body runs per chunk; receives batch list
    task = {
        'type': 'iterator',
        'collection': [1, 2, 3, 4, 5],
        'element': 'value',
        'chunk': 2,
        'task': make_python_task("return {'batch_sum': sum(batch)}"),
    }
    res = execute_task(task, 'iter', ctx, jenv, {})
    assert res['status'] == 'success'
    sums = [x['batch_sum'] for x in res['data']]
    assert sums == [3, 7, 5]


def test_iterator_collection_from_task_payload():
    jenv = Environment()
    cities = [
        {'name': 'London', 'lat': 51.51, 'lon': -0.13},
        {'name': 'Paris', 'lat': 48.85, 'lon': 2.35},
        {'name': 'Berlin', 'lat': 52.52, 'lon': 13.41},
    ]
    ctx = {
        'workload': {},
        'execution_id': 'test-exec',
        'data': {'cities': cities},
    }
    task = {
        'type': 'iterator',
        'element': 'city',
        'task': make_python_task("return {'name': value['name'], 'lat': value['lat']}")
    }

    res = execute_task(task, 'iter', ctx, jenv, {'cities': cities})
    assert res['status'] == 'success'
    payload = res['data']
    assert [row['name'] for row in payload] == ['London', 'Paris', 'Berlin']
    assert payload[0]['lat'] == pytest.approx(51.51)
