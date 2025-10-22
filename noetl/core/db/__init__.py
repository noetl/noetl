"""
noetl.core.db
=============

Database abstraction and utility functions for NoETL core components.

This package provides helpers for database connections, migrations, and
transaction management. It is used by only the server to interact with the PostgreSQL.

!!! DONT import this package in steps worked with databases.

All state is persisted in PostgreSQL, and this package centralizes access
patterns for reliability and maintainability.
"""