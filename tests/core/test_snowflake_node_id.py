from __future__ import annotations


def test_snowflake_node_id_ignores_topology_node_name():
    from noetl.core.common import _snowflake_node_id_from_env

    assert _snowflake_node_id_from_env({"NOETL_NODE_ID": "noetl-control-plane"}) == 0


def test_snowflake_node_id_prefers_numeric_specific_env():
    from noetl.core.common import _snowflake_node_id_from_env

    assert (
        _snowflake_node_id_from_env(
            {
                "NOETL_NODE_ID": "noetl-control-plane",
                "NOETL_SHARD_ID": "2",
                "NOETL_SNOWFLAKE_NODE_ID": "1025",
            }
        )
        == 1
    )


def test_snowflake_node_id_falls_back_to_shard_id():
    from noetl.core.common import _snowflake_node_id_from_env

    assert _snowflake_node_id_from_env({"NOETL_SHARD_ID": "17"}) == 17
