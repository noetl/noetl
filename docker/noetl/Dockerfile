FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get --no-install-recommends install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    libpq-dev \
    cargo \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/noetl

COPY pyproject.toml ./
COPY uv.lock* ./

RUN uv venv && \
    uv sync --frozen --no-dev --no-install-project

COPY LICENSE README.md ./
COPY noetl ./noetl
COPY ui ./ui

RUN uv pip install -e .

FROM python:3.12-slim AS production

RUN apt-get update && apt-get --no-install-recommends install -y \
    curl \
    wget \
    unzip \
    libpq-dev \
    libnss3 \
    libgconf-2-4 \
    libxss1 \
    fonts-liberation \
    libappindicator1 \
    libasound2 \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

COPY --from=builder /opt/noetl/.venv /opt/noetl/.venv

WORKDIR /opt/noetl

COPY --from=builder /opt/noetl/noetl ./noetl
COPY --from=builder /opt/noetl/ui ./ui
COPY --from=builder /opt/noetl/pyproject.toml ./
COPY --from=builder /opt/noetl/LICENSE ./
COPY --from=builder /opt/noetl/README.md ./

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/opt/noetl:$PYTHONPATH"
ENV PATH="/opt/noetl/.venv/bin:$PATH"

EXPOSE 8080

CMD ["python", "-m", "uvicorn", "--factory", "noetl.main:create_app", "--host", "0.0.0.0", "--port", "8080", "--reload"]