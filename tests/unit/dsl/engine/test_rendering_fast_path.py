from types import SimpleNamespace

from jinja2 import Environment

from noetl.core.dsl.engine.executor.rendering import RenderingMixin


class _TemplateCache:
    def get_or_compile(self, env, template_str):
        return env.from_string(template_str)


class _Renderer(RenderingMixin):
    def __init__(self, jinja_env):
        self.jinja_env = jinja_env
        self._template_cache = _TemplateCache()


def test_render_template_resolves_rows_from_reference_envelope(monkeypatch):
    renderer = _Renderer(Environment())
    rows = [{"patient_id": 1}, {"patient_id": 2}]

    monkeypatch.setattr(
        "noetl.core.dsl.engine.executor.rendering._resolve_reference_sync_for_fast_path",
        lambda reference: rows,
    )

    context = {
        "claim_patients_for_assessments": {
            "status": "success",
            "reference": {
                "kind": "temp_ref",
                "ref": "noetl://execution/exec-1/result/claim/rows",
            },
            "context": {"row_count": 2},
            "row_count": 2,
        }
    }

    assert renderer._render_template("{{ claim_patients_for_assessments.rows }}", context) == rows


def test_render_template_fallback_wraps_step_results_with_proxy():
    renderer = _Renderer(Environment())
    context = {
        "claim_patients_for_assessments": {
            "rows": [{"patient_id": 1}],
            "status": "success",
        },
        "ctx": {},
        "iter": {},
        "event": SimpleNamespace(),
    }

    assert renderer._render_template("{{ claim_patients_for_assessments.rows[0].patient_id }}", context) == "1"


def test_render_template_fallback_handles_nested_data_reference(monkeypatch):
    renderer = _Renderer(Environment())
    rows = [{"patient_id": 7}]

    monkeypatch.setattr(
        "noetl.core.dsl.render._resolve_reference_sync",
        lambda reference: rows,
    )

    context = {
        "claim_patients_for_conditions": {
            "status": "success",
            "data": {
                "reference": {
                    "kind": "temp_ref",
                    "ref": "noetl://execution/exec-1/result/claim-conditions/rows",
                }
            },
        },
        "ctx": {},
        "iter": {},
        "event": SimpleNamespace(),
    }

    assert renderer._render_template("{{ claim_patients_for_conditions.rows[0].patient_id }}", context) == "7"