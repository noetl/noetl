# `ci/manifests/` moved to `noetl/ops`

NoETL operational manifests (Kubernetes YAML for the worker
Deployment, NATS, Postgres, gateway, etc.) now live exclusively
in the [`noetl/ops`](https://github.com/noetl/ops) repo at
[`ci/manifests/`](https://github.com/noetl/ops/tree/main/ci/manifests).

Previously this repo carried a parallel copy under
`noetl/noetl/ci/manifests/`. That directory was deleted as part
of Scope B of the v2-spec close-out consolidation (May 2026); see
the commit history of this directory for the migration boundary.

## Where to find what

| Looking for | Where |
|---|---|
| Application code (Python, DSL, generators) | This repo (`noetl/noetl`) |
| Operational manifests (kubectl-applyable YAML) | `noetl/ops` → [`ci/manifests/`](https://github.com/noetl/ops/tree/main/ci/manifests) |
| Deployment automation playbooks | `noetl/ops` → [`automation/development/noetl.yaml`](https://github.com/noetl/ops/blob/main/automation/development/noetl.yaml) and friends |
| Application API wiki | <https://github.com/noetl/noetl/wiki> |
| Operational wiki (manifests, install, tuning) | <https://github.com/noetl/ops/wiki> |

## Why the split

- `noetl/ops/automation/development/noetl.yaml` is the playbook
  that drives `noetl k8s deploy`; it now reads its manifests
  from a local `ci/manifests/...` path rather than via a cross-
  repo `$NOETL_REPO/ci/manifests/...` reference.
- New operational manifests (KEDA, NATS supercluster, future
  cluster-aware routing, per-tenant accounts) belong next to
  the playbook that applies them, not next to the Python that
  generates them.
- Drift between two parallel `ci/manifests/` directories had
  already started accumulating before the consolidation.

## For agents / automated tooling

If you're scripted to look at `noetl/noetl/ci/manifests/...`,
update the path to `noetl/ops/ci/manifests/...`. The wiki rule
codifying this lives in
[`ai-meta/agents/rules/ops-deploy.md`](https://github.com/noetl/ai-meta/blob/main/agents/rules/ops-deploy.md).
