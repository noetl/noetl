from __future__ import annotations

import json


def test_prepare_event_payload_enriches_worker_topology(monkeypatch):
    from noetl.core.runtime import events

    monkeypatch.setattr(events, "_cached_worker_settings", None)
    monkeypatch.setattr(events, "_get_worker_settings", lambda: None)
    monkeypatch.setenv("NOETL_WORKER_ID", "worker-a")
    monkeypatch.setenv("NOETL_WORKER_POOL_NAME", "worker-cpu-01")
    monkeypatch.setenv("NOETL_WORKER_POOL_RUNTIME", "cpu")
    monkeypatch.setenv("NOETL_NODE_ID", "node-a")
    monkeypatch.setenv("NOETL_CLUSTER_ID", "cluster-a")
    monkeypatch.setenv("NOETL_REGION", "us-central1")
    monkeypatch.setenv("NOETL_ZONE", "us-central1-a")

    _url, body = events._prepare_event_payload(
        {
            "execution_id": "7",
            "event_type": "worker.test",
            "worker_id": "worker-a",
            "tenant_id": "tenant-a",
            "organization_id": "org-a",
        },
        "http://noetl",
    )
    payload = json.loads(body)

    assert payload["meta"]["locality"] == {
        "node_id": "node-a",
        "cluster_id": "cluster-a",
        "region": "us-central1",
        "zone": "us-central1-a",
        "worker_pool": "worker-cpu-01",
        "runtime": "cpu",
    }
    assert (
        payload["meta"]["worker_locator"]
        == "noetl://tenant/tenant-a/org/org-a/cluster/cluster-a/node/node-a/worker/worker-cpu-01"
    )
    assert payload["trace_component"]["worker"]["pool"] == "worker-cpu-01"


def test_prepare_event_payload_preserves_explicit_worker_topology(monkeypatch):
    from noetl.core.runtime import events

    monkeypatch.setattr(events, "_cached_worker_settings", None)
    monkeypatch.setattr(events, "_get_worker_settings", lambda: None)
    monkeypatch.setenv("NOETL_WORKER_POOL_NAME", "worker-cpu-01")
    monkeypatch.setenv("NOETL_WORKER_POOL_RUNTIME", "cpu")
    monkeypatch.setenv("NOETL_NODE_ID", "env-node")
    monkeypatch.setenv("NOETL_CLUSTER_ID", "env-cluster")

    explicit_locality = {
        "cluster_id": "cluster-b",
        "node_id": "node-b",
        "worker_pool": "worker-gpu-01",
        "runtime": "gpu",
    }

    _url, body = events._prepare_event_payload(
        {
            "execution_id": "8",
            "event_type": "worker.test",
            "worker_id": "worker-b",
            "tenant_id": "tenant-b",
            "organization_id": "org-b",
            "meta": {"locality": explicit_locality},
        },
        "http://noetl",
    )
    payload = json.loads(body)

    assert payload["meta"]["locality"] == explicit_locality
    assert (
        payload["meta"]["worker_locator"]
        == "noetl://tenant/tenant-b/org/org-b/cluster/cluster-b/node/node-b/worker/worker-gpu-01"
    )
