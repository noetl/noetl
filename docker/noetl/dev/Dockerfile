FROM rust:1.82-slim AS ehdb-helper

ARG EHDB_REF=0dc2016f4b692d3d868ccbc3918900962a880ca1

RUN apt-get update && apt-get --no-install-recommends install -y \
    ca-certificates \
    git \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /tmp/ehdb

RUN git init . \
    && git remote add origin https://github.com/noetl/ehdb.git \
    && git fetch --depth 1 origin "${EHDB_REF}" \
    && git -c advice.detachedHead=false checkout FETCH_HEAD \
    && cargo build --release --locked -p ehdb-reference --bin ehdb-local-reference

FROM python:3.12-slim AS builder

# Install uv directly instead of copying from ghcr.io
RUN apt-get update && apt-get --no-install-recommends install -y \
    curl \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /bin/uv \
    && mv /root/.local/bin/uvx /bin/uvx

WORKDIR /opt/noetl

COPY pyproject.toml ./
COPY uv.lock* ./

RUN uv venv && \
    uv sync --frozen --no-dev --no-install-project

COPY noetl ./noetl
COPY scripts ./scripts
COPY LICENSE README.md ./

RUN uv pip install -e .

FROM python:3.12-slim AS production

LABEL org.opencontainers.image.source=https://github.com/noetl/noetl
LABEL org.opencontainers.image.licenses=MIT

# kubectl + helm are first-class tool dependencies for `kind: shell`
# steps in lifecycle agents (e.g. the kubernetes MCP server's
# automation/agents/kubernetes/lifecycle/{deploy,undeploy,...}). The
# noetl worker dispatches those agents in-process; without these
# binaries on PATH every helm-driven deploy fails with
# "helm: not found".
#
# Multi-arch handled via dpkg --print-architecture (amd64 / arm64).
# Versions pinned to recent stable releases — bump at the same
# cadence as the upstream release notes.
ARG KUBECTL_VERSION=v1.30.5
ARG HELM_VERSION=v3.16.2

RUN apt-get update && apt-get --no-install-recommends install -y \
    curl \
    libpq-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && DPKG_ARCH="$(dpkg --print-architecture)" \
    && curl -fsSLo /usr/local/bin/kubectl \
         "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${DPKG_ARCH}/kubectl" \
    && chmod +x /usr/local/bin/kubectl \
    && kubectl version --client \
    && curl -fsSLo /tmp/helm.tar.gz \
         "https://get.helm.sh/helm-${HELM_VERSION}-linux-${DPKG_ARCH}.tar.gz" \
    && tar -xzf /tmp/helm.tar.gz -C /tmp \
    && mv "/tmp/linux-${DPKG_ARCH}/helm" /usr/local/bin/helm \
    && chmod +x /usr/local/bin/helm \
    && rm -rf /tmp/helm.tar.gz "/tmp/linux-${DPKG_ARCH}" \
    && helm version --short

# ENV TZ=America/Chicago
# RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=builder /opt/noetl/.venv /opt/noetl/.venv
COPY --from=ehdb-helper /tmp/ehdb/target/release/ehdb-local-reference /usr/local/bin/ehdb-local-reference

WORKDIR /opt/noetl

COPY --from=builder /opt/noetl/noetl ./noetl
COPY --from=builder /opt/noetl/scripts ./scripts
COPY --from=builder /opt/noetl/pyproject.toml ./
COPY --from=builder /opt/noetl/LICENSE ./
COPY --from=builder /opt/noetl/README.md ./

RUN ehdb-local-reference --help >/dev/null

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/opt/noetl"
ENV PATH="/opt/noetl/.venv/bin:$PATH"

# Default command: Use Python directly (more reliable across architectures)
# Rust CLI can be added manually: noetl server start --host 0.0.0.0 --port 8082
CMD ["python", "-m", "noetl.server", "--host", "0.0.0.0", "--port", "8082", "--init-db"]
