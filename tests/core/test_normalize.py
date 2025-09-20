from noetl.core.dsl.normalize import normalize_step


def test_normalize_aliases_to_data():
    step = {
        'type': 'http',
        'with': {'a': 1, 'b': 2},
        'params': {'b': 9, 'c': 3},
        'args': {'d': 4},
        'data': {'b': 5, 'e': 6},
    }
    out = normalize_step(step)
    assert out['data']['a'] == 1
    # params/with merged, but explicit data wins on conflicts
    assert out['data']['b'] == 5
    assert out['data']['c'] == 3
    assert out['data']['d'] == 4
    assert out['data']['e'] == 6
    # legacy keys removed
    assert 'with' not in out and 'params' not in out and 'args' not in out


def test_normalize_loop_to_iterator():
    step = {
        'step': 'cities',
        'loop': {
            'in': [1, 2, 3],
            'iterator': 'value'
        },
        'task': {'type': 'python', 'code': 'def main(value):\n  return value'}
    }
    out = normalize_step(step)
    assert out['type'] == 'iterator'
    assert out['data'] == [1, 2, 3]
    assert out['element'] == 'value'
    assert 'loop' not in out
