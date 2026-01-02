FROM node:20-alpine AS ui-builder
WORKDIR /ui
COPY ui-src/package.json ui-src/package-lock.json ./ui-src/
RUN cd ui-src && npm ci --verbose
COPY ui-src ./ui-src
ENV VITE_API_BASE_URL=/api
RUN cd ui-src && npm run build

FROM rust:1.83-slim AS rust-builder
WORKDIR /build
RUN apt-get update && apt-get install -y pkg-config libssl-dev && rm -rf /var/lib/apt/lists/*
COPY noetlctl/Cargo.toml noetlctl/Cargo.lock ./
COPY noetlctl/src ./src
RUN cargo build --release

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
COPY --from=ui-builder /ui/ui-src/dist ./noetl/core/ui

COPY LICENSE README.md ./

RUN uv pip install -e .

FROM python:3.12-slim AS production

LABEL org.opencontainers.image.source=https://github.com/noetl/noetl
LABEL org.opencontainers.image.licenses=MIT

RUN apt-get update && apt-get --no-install-recommends install -y \
    curl \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ENV TZ=America/Chicago
# RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=builder /opt/noetl/.venv /opt/noetl/.venv
COPY --from=rust-builder /build/target/release/noetl /usr/local/bin/noetl

WORKDIR /opt/noetl

COPY --from=builder /opt/noetl/noetl ./noetl
COPY --from=builder /opt/noetl/pyproject.toml ./
COPY --from=builder /opt/noetl/LICENSE ./
COPY --from=builder /opt/noetl/README.md ./

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/opt/noetl"
ENV PATH="/opt/noetl/.venv/bin:$PATH"

ENV NOETL_ENABLE_UI=false

# Default command runs the server, but can be overridden with environment variables:
# - Set NOETL_RUN_MODE=server for the default server mode
# - Set NOETL_RUN_MODE=worker and NOETL_PLAYBOOK_PATH for worker mode
# - Set NOETL_RUN_MODE=cli for CLI mode
CMD ["python", "-m", "noetl.main", "server", "start", "--host", "0.0.0.0", "--port", "8080"]

# ===
