# Build and push NoETL image

Public repository: `ghcr.io/noetl`

## Requirements:
- docker

## Create personal access token (PAT)

1. In GitHub go to:   
Settings → Developer settings → Personal access tokens → Tokens (classic) → Generate new token (classic).

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
--progress plain --tag ghcr.io/noetl/noetl:v1.0.0 \
--file docker/noetl/dev/Dockerfile .
```