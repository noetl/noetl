"""
noetl.core.db
=============

Database abstraction and utility functions for NoETL core components.

This package provides helpers for database connections, migrations, and
transaction management. It is used by only the server to interact with the PostgreSQL.

!!! DONT import this package in steps worked with databases.

All state is persisted in PostgreSQL, and this package centralizes access
patterns for reliability and maintainability.

TODO open and close pool using app lifespan events.
using this example
async with AsyncConnectionPool(dsn, kwargs={"row_factory": dict_row}) as pool:
    async with pool.connection() as conn:
        async with conn.transaction():
            await conn.execute("INSERT INTO logs (event) VALUES (%s)", ("ok",))
"""