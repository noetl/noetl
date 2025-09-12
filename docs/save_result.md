if the attribute "save" is defined for the step action type, the result will be saved to the the supported storage.

Storages:
- event_log table result column
- postgres table when postgres connection and table name are defined, or insert statement.
- GS/S3 object when gs/s3 connection and bucket name are defined, or insert statement.
- Snowflake table when snowflake connection and table name are defined, or insert statement.
- BigQuery table when bigquery connection and table name are defined, or insert statement.
- DuckDB table when duckdb connection and table name are defined, or insert statement.
- local file when a local file path is defined.

If storage is not defined, the result will be saved to the event_log table.
If save is not defined for the step action type, the result will not be saved.
