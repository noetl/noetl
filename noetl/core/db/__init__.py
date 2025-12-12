"""
noetl.core.db
=============

Database abstraction and utility functions for NoETL core components.

This package provides helpers for database connections, migrations, and
transaction management. It is used by only the server to interact with the PostgreSQL.

!!! DONT import this package in steps worked with databases.

All state is persisted in PostgreSQL, and this package centralizes access
patterns for reliability and maintainability.

Connection Pool Management:
--------------------------
The current implementation uses a simple connection pattern via get_pool_connection()
which creates connections on-demand using psycopg.AsyncConnection.connect().

For production deployments with high concurrency, consider implementing a connection
pool using psycopg_pool.AsyncConnectionPool with app lifespan events:

    async with AsyncConnectionPool(dsn, kwargs={"row_factory": dict_row}) as pool:
        async with pool.connection() as conn:
            async with conn.transaction():
                await conn.execute("INSERT INTO logs (event) VALUES (%s)", ("ok",))

See: https://www.psycopg.org/psycopg3/docs/advanced/pool.html
"""