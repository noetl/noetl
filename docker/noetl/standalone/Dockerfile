FROM python:3.12-slim AS base

LABEL maintainer="Kadyapam"
LABEL description="NoETL Server from PyPI"

ARG NOETL_VERSION=latest

RUN apt-get update && apt-get install -y \
    curl \
    git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash noetl

WORKDIR /opt/noetl

RUN pip install --no-cache-dir --upgrade pip

FROM base AS final

WORKDIR /opt/noetl

RUN if [ "$NOETL_VERSION" = "latest" ]; then \
        echo "Installing latest noetl version" && \
        pip install --no-cache-dir noetl; \
    else \
        echo "Installing noetl version $NOETL_VERSION" && \
        pip install --no-cache-dir noetl==$NOETL_VERSION; \
    fi

RUN mkdir -p /opt/noetl/data /opt/noetl/logs && \
    chown -R noetl:noetl /opt/noetl

USER noetl

EXPOSE 8080 8081 8082 8084

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENV NOETL_LOG_LEVEL=INFO
ENV NOETL_DATA_PATH=/opt/noetl/data
ENV NOETL_PLAYBOOKS_PATH=/opt/noetl/playbooks

# Default command runs the server, but can be overridden with environment variables:
# - Set NOETL_RUN_MODE=server for server mode (default)
# - Set NOETL_RUN_MODE=worker and NOETL_PLAYBOOK_PATH for worker mode
# - Set NOETL_RUN_MODE=cli for CLI mode
CMD ["noetl", "server", "start", "--host", "0.0.0.0", "--port", "8084", "--debug"]
