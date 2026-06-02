"""Unit tests for the KEDA scaler generator (v2 spec Phase 4 round 2)."""

from __future__ import annotations

import pytest
import yaml

from noetl.core.runtime.keda import (
    DEFAULT_ACTIVATION_LAG_THRESHOLD,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_LAG_THRESHOLD,
    DEFAULT_MAX_REPLICAS,
    DEFAULT_MIN_REPLICAS,
    DEFAULT_NATS_ACCOUNT,
    DEFAULT_NATS_MONITORING_ENDPOINT,
    DEFAULT_NATS_STREAM,
    DEFAULT_POLLING_INTERVAL_SECONDS,
    ScaledObjectSpec,
    build_worker_scaledobject,
    dump_scaledobject_yaml,
    worker_pool_segment,
)


# Worker-pool URN used for the existing single-pool deployment in
# noetl/ops at ci/manifests/noetl/worker-deployment.yaml.
# Reused across tests so we don't repeat the literal.
EXISTING_URN = "noetl://tenant/default/org/default/worker/worker-cpu-01"


def _default_spec(**overrides) -> ScaledObjectSpec:
    base = {
        "worker_pool_urn": EXISTING_URN,
        "deployment": "noetl-worker",
    }
    base.update(overrides)
    return ScaledObjectSpec(**base)


def test_worker_pool_segment_extracts_last_safe_segment():
    assert worker_pool_segment(EXISTING_URN) == "worker-cpu-01"


def test_worker_pool_segment_collapses_unsafe_chars():
    """Non-NATS-safe chars collapse to '_' per round 1's mapping."""
    urn = "noetl://tenant/acme/org/r&d/worker/cpu pool"
    assert worker_pool_segment(urn) == "cpu_pool"


def test_build_worker_scaledobject_uses_urn_for_scaler_name():
    out = build_worker_scaledobject(_default_spec())
    assert out["metadata"]["name"] == "noetl-worker-scaler-worker-cpu-01"


def test_build_worker_scaledobject_honors_explicit_scaler_name():
    out = build_worker_scaledobject(_default_spec(scaler_name="custom-name"))
    assert out["metadata"]["name"] == "custom-name"


def test_build_worker_scaledobject_derives_consumer_from_urn():
    """Without an explicit consumer, derive from URN subject form."""
    out = build_worker_scaledobject(_default_spec())
    consumer = out["spec"]["triggers"][0]["metadata"]["consumer"]
    # URN → subject "noetl.tenant.default.org.default.worker.worker-cpu-01"
    # → strip "noetl." → "tenant.default.org.default.worker.worker-cpu-01"
    # → "." → "_" → "tenant_default_org_default_worker_worker-cpu-01"
    assert consumer == "tenant_default_org_default_worker_worker-cpu-01"


def test_build_worker_scaledobject_honors_explicit_consumer():
    out = build_worker_scaledobject(
        _default_spec(nats_consumer="noetl_worker_pool")
    )
    assert out["spec"]["triggers"][0]["metadata"]["consumer"] == "noetl_worker_pool"


def test_build_worker_scaledobject_emits_keda_v1alpha1_schema():
    out = build_worker_scaledobject(_default_spec())

    assert out["apiVersion"] == "keda.sh/v1alpha1"
    assert out["kind"] == "ScaledObject"
    assert out["metadata"]["namespace"] == "noetl"
    assert out["spec"]["scaleTargetRef"]["name"] == "noetl-worker"
    assert out["spec"]["minReplicaCount"] == DEFAULT_MIN_REPLICAS
    assert out["spec"]["maxReplicaCount"] == DEFAULT_MAX_REPLICAS
    assert out["spec"]["pollingInterval"] == DEFAULT_POLLING_INTERVAL_SECONDS
    assert out["spec"]["cooldownPeriod"] == DEFAULT_COOLDOWN_SECONDS

    triggers = out["spec"]["triggers"]
    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger["type"] == "nats-jetstream"
    md = trigger["metadata"]
    assert md["natsServerMonitoringEndpoint"] == DEFAULT_NATS_MONITORING_ENDPOINT
    assert md["account"] == DEFAULT_NATS_ACCOUNT
    # Live-validation pin: the default must match the NATS account
    # the noetl user actually lives in. Pointing KEDA at the wrong
    # account (e.g. the global "$G") returns num_pending: 0
    # silently and breaks scaling. See noetl/ops at
    # ci/manifests/nats/nats.yaml.
    assert DEFAULT_NATS_ACCOUNT == "NOETL"
    assert md["stream"] == DEFAULT_NATS_STREAM
    # KEDA requires every metadata value to be a string, even for
    # numeric fields. Guard the contract.
    assert md["lagThreshold"] == str(DEFAULT_LAG_THRESHOLD)
    assert md["activationLagThreshold"] == str(DEFAULT_ACTIVATION_LAG_THRESHOLD)
    assert md["useHttps"] == "false"
    assert isinstance(md["lagThreshold"], str)
    assert isinstance(md["activationLagThreshold"], str)


def test_build_worker_scaledobject_labels_carry_pool_segment():
    out = build_worker_scaledobject(_default_spec())
    labels = out["metadata"]["labels"]
    assert labels["app"] == "noetl-worker"
    assert labels["worker-pool"] == "worker-cpu-01"
    assert labels["managed-by"] == "noetl"


def test_build_worker_scaledobject_rejects_non_tenant_urn():
    with pytest.raises(ValueError, match="tenant-shaped URN"):
        build_worker_scaledobject(
            _default_spec(worker_pool_urn="noetl://execution/12345")
        )


def test_build_worker_scaledobject_rejects_dataset_urn():
    with pytest.raises(ValueError, match="tenant-shaped URN"):
        build_worker_scaledobject(
            _default_spec(
                worker_pool_urn="noetl://dataset/sales-2026"
            )
        )


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"min_replicas": -1}, "min_replicas"),
        ({"min_replicas": 5, "max_replicas": 3}, "max_replicas"),
        ({"lag_threshold": 0}, "lag_threshold"),
        ({"lag_threshold": -1}, "lag_threshold"),
        ({"activation_lag_threshold": -1}, "activation_lag_threshold"),
        ({"polling_interval_seconds": 0}, "polling_interval_seconds"),
        ({"cooldown_seconds": 0}, "cooldown_seconds"),
    ],
)
def test_build_worker_scaledobject_rejects_invalid_numerics(overrides, match):
    with pytest.raises(ValueError, match=match):
        build_worker_scaledobject(_default_spec(**overrides))


def test_build_worker_scaledobject_with_full_locality():
    """URN with region/zone/cluster set produces locality-rich consumer."""
    urn = (
        "noetl://tenant/acme/org/research/region/us-east1/zone/us-east1-b"
        "/cluster/prod/worker/gpu-large"
    )
    out = build_worker_scaledobject(
        _default_spec(worker_pool_urn=urn, deployment="noetl-worker-gpu")
    )

    assert out["metadata"]["name"] == "noetl-worker-gpu-scaler-gpu-large"
    consumer = out["spec"]["triggers"][0]["metadata"]["consumer"]
    assert consumer == (
        "tenant_acme_org_research_region_us-east1_zone_us-east1-b"
        "_cluster_prod_worker_gpu-large"
    )
    assert out["metadata"]["labels"]["worker-pool"] == "gpu-large"


def test_build_worker_scaledobject_min_replicas_zero_allowed():
    """KEDA's activation knob lets min=0 work as scale-to-zero."""
    out = build_worker_scaledobject(_default_spec(min_replicas=0))
    assert out["spec"]["minReplicaCount"] == 0


def test_build_worker_scaledobject_default_single_trigger():
    """Default spec (no additional_consumers) emits a single trigger.

    Back-compat: existing callers that don't know about
    `additional_consumers` continue to get today's single-trigger
    ScaledObject shape.
    """
    out = build_worker_scaledobject(_default_spec(nats_consumer="noetl_worker_pool"))
    triggers = out["spec"]["triggers"]
    assert len(triggers) == 1
    assert triggers[0]["metadata"]["consumer"] == "noetl_worker_pool"


def test_build_worker_scaledobject_additional_consumers_emit_extra_triggers():
    """Per noetl/ai-meta#42 PR-4a: additional_consumers stack into
    extra triggers, primary first.  KEDA picks MAX(replicas) across
    triggers so the pool scales on whichever consumer has the
    largest backlog.
    """
    out = build_worker_scaledobject(
        _default_spec(
            nats_consumer="noetl_worker_pool",
            additional_consumers=(
                "noetl_worker_pool_shared",
                "noetl_worker_pool_python",
            ),
        )
    )
    triggers = out["spec"]["triggers"]
    assert len(triggers) == 3
    consumers = [trigger["metadata"]["consumer"] for trigger in triggers]
    assert consumers == [
        "noetl_worker_pool",
        "noetl_worker_pool_shared",
        "noetl_worker_pool_python",
    ]
    # All triggers share the same threshold + monitoring endpoint
    # (the spec's defaults).
    for trigger in triggers:
        assert trigger["type"] == "nats-jetstream"
        assert trigger["metadata"]["lagThreshold"] == "10"
        assert trigger["metadata"]["account"] == "NOETL"


def test_build_worker_scaledobject_empty_additional_consumers_is_single_trigger():
    """Empty tuple for `additional_consumers` is equivalent to the
    default (single-trigger), not "primary + zero extras = some other
    shape".
    """
    out = build_worker_scaledobject(
        _default_spec(
            nats_consumer="noetl_worker_pool",
            additional_consumers=(),
        )
    )
    assert len(out["spec"]["triggers"]) == 1


def test_dump_scaledobject_yaml_round_trip():
    out = build_worker_scaledobject(_default_spec())
    rendered = dump_scaledobject_yaml(out)
    reloaded = yaml.safe_load(rendered)
    assert reloaded == out


def test_dump_scaledobject_yaml_preserves_top_level_key_order():
    """apiVersion → kind → metadata → spec ordering survives serialization."""
    out = build_worker_scaledobject(_default_spec())
    rendered = dump_scaledobject_yaml(out)
    lines = [line for line in rendered.splitlines() if line and not line.startswith(" ")]
    # Top-level keys (no indent) in order
    assert lines[0].startswith("apiVersion:")
    assert lines[1].startswith("kind:")
    assert lines[2].startswith("metadata:")
    assert lines[3].startswith("spec:")


# ----------------------------------------------------------------------------
# Sample-manifest drift guards
#
# The ops repo at `noetl/ops/ci/manifests/keda/scaledobject-*.yaml` checks
# in the generator output verbatim so operators can `kubectl apply -f` it
# directly.  These fixtures under `tests/fixtures/keda/` are the test-side
# source of truth — if a generator change moves the YAML body, this guard
# fails and the operator must regenerate both the noetl/noetl fixture and
# the noetl/ops manifest before the change can land.
#
# The fixtures intentionally omit any header comments (they're the YAML
# body only).  The ops manifests wrap the same body in operator-facing
# header comments documenting the regen recipe.
#
# Pool inventory (kept in lockstep with `noetl/ops/ci/manifests/keda/`):
#
#   - `worker-cpu-01` — Python `noetl-worker` deployment (the original
#     single-pool sample from the v2-spec Phase 4 round).
#   - `worker-rust-pool` — Rust `noetl-worker-rust` deployment (added
#     2026-06-02 alongside R-3 Phase B-4 dual-scaling; both pools share
#     the same NATS stream + consumer, so adding the Rust-pool scaler
#     gives KEDA-driven autoscaling on both halves of the worker fleet).
# ----------------------------------------------------------------------------

import pathlib

_FIXTURE_DIR = pathlib.Path(__file__).resolve().parents[2] / "fixtures" / "keda"


@pytest.mark.parametrize(
    "fixture_name, spec",
    [
        (
            # Python pool: three triggers (legacy + shared + python
            # consumers) per noetl/ai-meta#42 PR-4a.  KEDA picks the
            # MAX desired-replicas across the triggers so the pool
            # scales on whichever consumer has the largest backlog.
            "scaledobject-worker-cpu-01.yaml",
            ScaledObjectSpec(
                worker_pool_urn=(
                    "noetl://tenant/default/org/default/worker/worker-cpu-01"
                ),
                deployment="noetl-worker",
                nats_consumer="noetl_worker_pool",
                additional_consumers=(
                    "noetl_worker_pool_shared",
                    "noetl_worker_pool_python",
                ),
            ),
        ),
        (
            # Rust pool: single trigger on the shared consumer (Rust
            # workers only subscribe to .shared.> per PR-2b/PR-3).
            "scaledobject-worker-rust-pool.yaml",
            ScaledObjectSpec(
                worker_pool_urn=(
                    "noetl://tenant/default/org/default/worker/worker-rust-pool"
                ),
                deployment="noetl-worker-rust",
                nats_consumer="noetl_worker_pool_shared",
            ),
        ),
    ],
    ids=["worker-cpu-01-python-pool", "worker-rust-pool-rust-pool"],
)
def test_sample_manifest_matches_generator_output(fixture_name, spec):
    """Verify each checked-in pool sample matches what the generator emits.

    Catches drift between the noetl/noetl fixtures + the noetl/ops manifests
    + the live generator.  If this test fails, regenerate both files via
    the recipe in `noetl/ops/ci/manifests/keda/README.md` before merging
    any generator change.
    """
    fixture = _FIXTURE_DIR / fixture_name
    expected = fixture.read_text()
    actual = dump_scaledobject_yaml(build_worker_scaledobject(spec))
    assert actual == expected, (
        f"Drift detected for {fixture_name}.  Regenerate via the recipe "
        f"in `noetl/ops/ci/manifests/keda/README.md` and update both the "
        f"fixture under tests/fixtures/keda/ and the matching ops manifest."
    )


