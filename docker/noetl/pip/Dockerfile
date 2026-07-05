FROM rust:1.82-slim AS ehdb-helper

ARG EHDB_REF=3ae895016154f9e5537a61930aeba2788b814ed3

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

# Re-declare ARG - ARGs don't persist across FROM statements in multi-stage builds
ARG NOETL_VERSION=latest

WORKDIR /opt/noetl

RUN if [ "$NOETL_VERSION" = "latest" ]; then \
        echo "Installing latest noetl version" && \
        pip install --no-cache-dir noetl; \
    else \
        echo "Installing noetl version $NOETL_VERSION" && \
        pip install --no-cache-dir noetl==$NOETL_VERSION; \
    fi

COPY --from=ehdb-helper /tmp/ehdb/target/release/ehdb-local-reference /usr/local/bin/ehdb-local-reference

RUN ehdb-local-reference --help >/dev/null

RUN mkdir -p /opt/noetl/data /opt/noetl/logs && \
    chown -R noetl:noetl /opt/noetl

USER noetl

EXPOSE 8080 8081 8082 8084

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8084/health || exit 1

ENV NOETL_LOG_LEVEL=INFO
ENV NOETL_DATA_PATH=/opt/noetl/data
ENV NOETL_PLAYBOOKS_PATH=/opt/noetl/playbooks

CMD ["noetl", "server", "start", "--host", "0.0.0.0", "--port", "8084", "--debug"]
