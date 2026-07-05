# Build and push NoETL image

Public repository: `ghcr.io/noetl`

## Requirements:
- docker

## Create personal access token (PAT)

1. In GitHub go to:   
[Open Github profile settings](https://github.com/settings/profile) → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic).

2. Give it scopes: `read:packages`, `write:packages`.  
Save the token somewhere safe.

## Login to the repository

Put the token value into the **CR_PAT** environment variable  
```bash
export CR_PAT=ghp_XXXXXXXXXXXXXXXXXXXXXXXX
```

Authenticate Docker to ghcr.io
```bash
echo $CR_PAT | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
```

Official guide is [here](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry?utm_source=chatgpt.com#authenticating-with-a-personal-access-token-classic)

## Build and push multi-platform image
```bash
docker buildx build --push --platform linux/amd64,linux/arm64 --no-cache \
--progress plain --tag ghcr.io/noetl/noetl:v1.0.2 \
--file docker/noetl/dev/Dockerfile .
```

```bash
docker build --push --platform linux/amd64 --no-cache \
--progress plain --tag ghcr.io/noetl/noetl:v1.0.2 \
--file docker/noetl/dev/Dockerfile .
```

## EHDB integration is Rust-only

The Python images no longer bundle the `ehdb-local-reference` helper binary.
The EHDB (Event Horizon Database) integration is owned by the Rust worker
([`noetl/worker`](https://github.com/noetl/worker), `src/ehdb`), which links
the `ehdb-reference` crate **in process** — there is no subprocess helper and
no Python EHDB path (retired; see
[noetl/ehdb#234](https://github.com/noetl/ehdb/issues/234)). Production runs the
Rust worker, so that is the only EHDB path that executes.
