from jinja2 import Environment, BaseLoader, StrictUndefined
from noetl.core.dsl.render import render_template


def test_step_result_addressing_proxy():
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    ctx = {
        'workload': {},
        # Prior step plain dict should expose '.result' accessor
        'fetch_http': {'url': 'u', 'elapsed': 1.23},
    }
    out = render_template(env, "{{ fetch_http.result.url }}", ctx, strict_keys=True)
    assert out == 'u'


def test_step_result_addressing_default_elapsed():
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    ctx = {
        'workload': {},
        'fetch_http': {},
    }
    out = render_template(
        env,
        "{{ (fetch_http.result.elapsed | default(0)) if fetch_http.result is defined else 0 }}",
        ctx,
        strict_keys=True,
    )
    assert out == 0


def test_ctx_namespace_uses_plain_dict_lookup():
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    ctx = {
        'ctx': {
            'facility_mapping_id': 53,
            'facility_org_uuid': 'org-1',
        },
        'facility_mapping_id': 53,
        'workload': {},
    }

    out = render_template(env, "{{ ctx.facility_mapping_id }}", ctx, strict_keys=True)
    assert out == 53


def test_iter_namespace_uses_plain_dict_lookup():
    env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
    ctx = {
        'iter': {
            'patient': {
                'patient_id': 101,
            }
        },
        'workload': {},
    }

    out = render_template(env, "{{ iter.patient.patient_id }}", ctx, strict_keys=True)
    assert out == 101
