import pytest

from noetl.core.dsl.render import TaskResultProxy


def test_task_result_proxy_result_alias_returns_self_for_dict_payload():
    proxy = TaskResultProxy({"rows": [{"id": 1}], "status": "success"})

    assert proxy.result.rows[0]["id"] == 1
    assert proxy.result.status == "success"


def test_task_result_proxy_does_not_flatten_context_keys_to_top_level():
    proxy = TaskResultProxy(
        {
            "status": "COMPLETED",
            "context": {"facility_mapping_id": 46},
        }
    )

    with pytest.raises(AttributeError):
        _ = proxy.facility_mapping_id
    with pytest.raises(KeyError):
        _ = proxy["facility_mapping_id"]

    assert proxy.context.facility_mapping_id == 46
