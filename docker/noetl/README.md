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

## EHDB helper binary

NoETL can execute the bounded EHDB local-reference summary helper from
worker/playbook contexts. Images that include EHDB should place the
binary at one of these runtime paths:

- `/usr/local/bin/ehdb-local-reference`
- `/opt/noetl/bin/ehdb-local-reference`

An operator can override discovery with:

```bash
NOETL_EHDB_HELPER_BIN=/custom/path/ehdb-local-reference
```

Local ai-meta workspaces can also use the sibling EHDB build outputs
under `../ehdb/target/{release,debug}/ehdb-local-reference`. Validate a
runtime image or local checkout with:

```bash
python scripts/smoke_ehdb_local_reference_summary.py \
  --log /tmp/noetl-ehdb-smoke.jsonl
```

The in-repo Dockerfiles build the helper from `noetl/ehdb` using the
`EHDB_REF` build arg and copy only the compiled binary into the final
runtime image:

```bash
docker build \
  --build-arg EHDB_REF=3ae895016154f9e5537a61930aeba2788b814ed3 \
  --file docker/noetl/dev/Dockerfile .
```
