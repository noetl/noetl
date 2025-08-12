FROM node:20-alpine AS ui-builder
WORKDIR /ui
COPY ui-src/package.json ui-src/package-lock.json ./ui-src/
RUN cd ui-src && npm ci
COPY ui-src ./ui-src
RUN cd ui-src && npm run build

FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get --no-install-recommends install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/noetl

COPY pyproject.toml ./
COPY uv.lock* ./

RUN uv venv && \
    uv sync --frozen --no-dev --no-install-project

COPY noetl ./noetl
COPY --from=ui-builder /ui/ui-src/dist ./noetl/ui/build

COPY LICENSE README.md ./

RUN uv pip install -e .

FROM python:3.12-slim AS production

RUN apt-get update && apt-get --no-install-recommends install -y \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=builder /opt/noetl/.venv /opt/noetl/.venv

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
