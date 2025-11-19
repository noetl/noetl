"""
Custom exceptions for the DuckDB plugin.
"""

class DuckDBPluginError(Exception):
    """Base exception for DuckDB plugin errors."""
    pass


class ConnectionError(DuckDBPluginError):
    """Error establishing or managing DuckDB connection."""
    pass


class AuthenticationError(DuckDBPluginError):
    """Error with credential resolution or authentication."""
    pass


class ConfigurationError(DuckDBPluginError):
    """Error with task or plugin configuration."""
    pass


class SQLExecutionError(DuckDBPluginError):
    """Error executing SQL commands."""
    pass


class CloudStorageError(DuckDBPluginError):
    """Error with cloud storage operations."""
    pass


class ExtensionError(DuckDBPluginError):
    """Error with DuckDB extension management."""
    pass


class ExcelExportError(DuckDBPluginError):
    """Error raised while processing Excel export commands."""
    pass