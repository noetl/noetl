FROM node:20-alpine AS ui-builder
WORKDIR /ui
COPY ui-src/package.json ui-src/package-lock.json ./ui-src/
RUN cd ui-src && npm ci --verbose
COPY ui-src ./ui-src
ENV VITE_API_BASE_URL=/api
RUN cd ui-src && npm run build

# Rust builder stage - can be skipped if using pre-compiled binary
# To use pre-compiled binary: docker build --build-arg USE_PREBUILT_BINARY=true
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

# Optional: Copy pre-compiled Rust binary if available
# Binaries must be built separately using: scripts/build_rust_multiarch.sh
# For now, Rust CLI is optional - Python CLI works fine
# ARG TARGETARCH
# COPY noetlctl/target/x86_64-unknown-linux-gnu/release/noetl /usr/local/bin/noetl || echo "No Rust binary"

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

# Default command: Use Python directly (more reliable across architectures)
# Rust CLI can be used manually: noetl server start --host 0.0.0.0 --port 8082
CMD ["python", "-m", "noetl.server", "--host", "0.0.0.0", "--port", "8082", "--init-db"]

# ===
