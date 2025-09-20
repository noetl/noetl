from jinja2 import Environment, BaseLoader, StrictUndefined
from noetl.core.dsl.render import render_template


def test_step_result_addressing_proxy():
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    ctx = {
        'workload': {},
        # Prior step plain dict should expose '.result' accessor
        'fetch_http': {'data': {'url': 'u', 'elapsed': 1.23}},
    }
    out = render_template(env, "{{ fetch_http.result.data.url }}", ctx, strict_keys=True)
    assert out == 'u'


def test_step_result_addressing_default_elapsed():
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    ctx = {
        'workload': {},
        'fetch_http': {'data': {}},
    }
    out = render_template(
        env,
        "{{ (fetch_http.result.data.elapsed | default(0)) if fetch_http.result is defined and fetch_http.result.data is defined else 0 }}",
        ctx,
        strict_keys=True,
    )
    assert out == 0
