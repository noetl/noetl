"""DuckLake plugin error types."""


class DuckLakePluginError(Exception):
    """Base exception for DuckLake plugin errors."""
    pass


class CatalogConnectionError(DuckLakePluginError):
    """Error connecting to DuckLake catalog (Postgres metastore)."""
    pass


class CatalogNotFoundError(DuckLakePluginError):
    """DuckLake catalog does not exist."""
    pass


class DataPathError(DuckLakePluginError):
    """Error with data_path configuration."""
    pass


class SnapshotError(DuckLakePluginError):
    """Error related to DuckLake snapshots."""
    pass
