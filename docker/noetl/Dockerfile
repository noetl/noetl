FROM python:3.12-slim

RUN apt-get update \
 && apt-get --no-install-recommends install -y \
    curl wget unzip build-essential \
    libssl-dev libffi-dev libpq-dev cargo \
    libnss3 libgconf-2-4 libxss1 fonts-liberation libappindicator1 libasound2 xvfb \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
ENV TZ=America/Chicago
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone
WORKDIR /opt/noetl
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_PYTHON_PROJECT=/opt/noetl
ENV PYTHONPATH="$UV_PYTHON_PROJECT:$PYTHONPATH:/root/.local/lib/python3.12/site-packages/root/.local/bin:${PATH}"
COPY pyproject.toml ./
COPY noetl ./noetl
RUN uv lock && uv sync --frozen --no-cache && pip install --no-cache-dir uvicorn[standard]
EXPOSE 8080
CMD python -m uvicorn --factory noetl.server.app:create_app --host 0.0.0.0 --port 8080