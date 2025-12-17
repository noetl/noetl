from jinja2 import Environment
from noetl.tools import execute_task


def test_iterator_exposes_result_index_in_body():
    jenv = Environment()
    ctx = {'workload': {}, 'execution_id': 'exec-idx'}
    nested = {
        'type': 'python',
        'code': """
def main(idx=None):
    return {'idx': int(idx)}
""",
        'with': {'idx': "{{ http_loop.result_index }}"}
    }
    task = {
        'name': 'http_loop',
        'type': 'iterator',
        'data': [10, 20, 30],
        'element': 'item',
        'task': nested,
    }
    out = execute_task(task, 'http_loop', ctx, jenv, {})
    assert out['status'] == 'success'
    items = out['data']
    assert [x['idx'] for x in items] == [0, 1, 2]

