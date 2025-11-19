# Local DuckDB Artifacts

This directory hosts lightweight DuckDB scripts and outputs used for local testing without running the full NoETL stack.

## Files

| File | Description |
| --- | --- |
| `duckdb_local_parquet.duckdb` | SQL script that writes a sample table to `data/test/local_upload.parquet`, reads it back, and writes `data/test/local_download.parquet`. Useful for validating DuckDB + Parquet locally. |

## Usage

```bash
cd /Users/akuksin/projects/noetl/noetl
mkdir -p data/test
duckdb -init data/duckdb_local_parquet.duckdb
# (or) duckdb < data/duckdb_local_parquet.duckdb
```

After the script runs, inspect the generated Parquet files with DuckDB, pandas, or any Parquet reader. Feel free to copy/modify the script to point at other local files when iterating on playbook logic.
