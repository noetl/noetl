FROM jupyter/datascience-notebook:latest

RUN pip install --no-cache-dir \
    duckdb>=1.3.0 \
    duckdb-engine>=0.17.0 \
    polars[pyarrow]>=1.30.0 \
    matplotlib>=3.10.3 \
    networkx>=3.5 \
    pydot>=4.0.1 \
    jupysql>=0.11.1 \
    ipython-sql \
    psycopg[binary]>=3.2.7 \
    connectorx>=0.4.3 \
    fsspec>=2025.5.1 \
    gcsfs>=2025.5.1 \
    google-cloud-secret-manager>=2.24.0

RUN jupyter server extension enable jupysql