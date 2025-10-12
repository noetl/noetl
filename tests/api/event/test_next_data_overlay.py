from noetl.server.api.event.control.step import _choose_next


def test_next_prefers_data_overlay_when_present():
    base_ctx = {'workload': {}, 'A': {'foo': 1}}
    step_def = {
        'step': 'A',
        'next': [
            {'step': 'B', 'when': True, 'with': {'x': 1}, 'data': {'x': 2, 'y': 3}},
        ]
    }
    nm, payload = _choose_next(step_def, base_ctx)
    assert nm == 'B'
    assert payload == {'x': 2, 'y': 3}


def test_next_uses_with_when_data_missing():
    base_ctx = {'workload': {}, 'A': {'foo': 1}}
    step_def = {
        'step': 'A',
        'next': [
            {'step': 'C', 'when': True, 'with': {'k': 'v'}},
        ]
    }
    nm, payload = _choose_next(step_def, base_ctx)
    assert nm == 'C'
    assert payload == {'k': 'v'}

