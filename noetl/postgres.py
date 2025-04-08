import asyncio
import contextlib
import json
import re
from contextlib import asynccontextmanager
from typing import Optional, Tuple,  Union

from psycopg.errors import (
    ForeignKeyViolation,
    UniqueViolation,
    CheckViolation,
    NotNullViolation,
    IntegrityError,
)
from psycopg_pool import AsyncConnectionPool, PoolTimeout
from psycopg.rows import dict_row

from noetl.logger import setup_logger
logger = setup_logger(__name__, include_location=True)

class PostgresHandler:
    """Manages Postgres connection pool using psycopg3"""

    def __init__(self, config):
        self.config = config
        self.pool: Optional[AsyncConnectionPool] = None
        self.pool_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        """Perform initialization and setting the timezone."""
        if self._initialized:
            logger.debug("✅ Postgres handler already initialized.")
            return

        for attempt in range(3):
            try:
                await self.initialize_pool()
                async with self.pool.connection() as conn:
                    await conn.execute(f"SET TIME ZONE '{self.config.timezone}'")
                self._initialized = True
                logger.info("Postgres handler initialized successfully.")
                return
            except PoolTimeout as e:
                logger.warning(f"Connection timeout: {e}. Retrying in 5 seconds.")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error during initialization: {e}")
                if attempt == 2:
                    raise

    async def initialize_pool(self):
        """📌 Initialize the connection pool."""
        async with self.pool_lock:
            if self.pool is None:
                try:
                    self.pool = AsyncConnectionPool(
                        f"postgresql://{self.config.postgres_user}:{self.config.postgres_password}@"
                        f"{self.config.postgres_host}:{self.config.postgres_port}/{self.config.postgres_database}",
                        min_size=self.config.postgres_pool_min_size,
                        max_size=self.config.postgres_pool_max_size,
                        timeout=self.config.postgres_pool_timeout,
                        open=False
                    )
                    await self.pool.open()
                    logger.info("Postgres connection pool initialized successfully.")
                except Exception as e:
                    logger.error(f"Error initializing connection pool: {e}")
                    raise

    @contextlib.asynccontextmanager
    async def connect(self):
        """Connection from the pool and cleanup."""
        if not self.pool:
            await self.initialize_pool()

        for attempt in range(3):
            try:
                async with self.pool.connection() as conn:
                    # try:
                    if self.config.timezone:
                        await conn.execute(f"SET TIME ZONE '{self.config.timezone}'")
                    yield conn
                    return
            except PoolTimeout as e:
                logger.warning(f"Connection timeout: {e}. Retrying.")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error acquiring connection: {e}")
                if attempt == 2:
                    raise
            finally:
                logger.debug("Closing async connection generator.")

    async def execute_query(self, query: str, *args):
        """Execute database query."""
        async with self.connect() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                try:
                    logger.debug(f"Executing query: {query} | Args: {args}")
                    await cur.execute(query, args)
                    if cur.description:
                        return await cur.fetchall()
                except ForeignKeyViolation as e:
                    logger.error(f"Foreign Key Violation: {e}")
                    raise
                except UniqueViolation as e:
                    logger.error(f"Unique Constraint Violation: {e}")
                    raise
                except NotNullViolation as e:
                    logger.error(f"NOT NULL Constraint Violation: {e}")
                    raise
                except IntegrityError as e:
                    logger.error(f"Integrity Error: {e}")
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error executing query: {e}")
                    raise

    async def execute_sql(self, query: str, args: Tuple = ()):
        """
        Execute a stored procedure.
        The query should be formatted as "CALL proc_name(arg1, arg2, ...);"
        """
        if not self.pool:
            logger.error("Connection pool is not initialized.")
            return None

        async with self.connect() as conn:
            try:
                async with conn.cursor(row_factory=dict_row) as cur:
                    logger.debug(f"Calling procedure: {query} with args: {args}")
                    await cur.execute(query, args)

                    logger.info(f"Command executed successfully: {query}")
                    return None
            except Exception as e:
                logger.error(f"Error executing stored procedure '{query}': {e}")
                raise

    async def call_routine(self, query: str, args: Tuple = (), is_procedure: bool = False, fetch_all: bool = True):
        """Execute a Postgres function or stored procedure."""
        if not self.pool:
            logger.error("Connection pool is not initialized.")
            return None

        async with self.connect() as conn:
            try:
                async with conn.cursor(row_factory=dict_row) as cur:
                    if is_procedure:
                        procedure_call = f"CALL {query}({', '.join(['%s'] * len(args))})"
                        logger.debug(f"Calling procedure: {procedure_call} with args: {args}")
                        await cur.execute(procedure_call, args)
                        logger.info(f"Procedure '{query}' executed successfully.")
                        return None
                    else:
                        logger.debug(f"Executing function: {query} with args: {args}")
                        await cur.execute(query, args)

                        if fetch_all:
                            results = await cur.fetchall()
                        else:
                            results = await cur.fetchone()

                        logger.debug(f"Function results: {results}")
                        return results
            except ForeignKeyViolation as e:
                logger.error(f"Foreign Key Violation: {e}")
                raise
            except UniqueViolation as e:
                logger.error(f"Unique Constraint Violation: {e}")
                raise
            except NotNullViolation as e:
                logger.error(f"NOT NULL Constraint Violation: {e}")
                raise
            except IntegrityError as e:
                logger.error(f"Integrity Error: {e}")
                raise
            except Exception as e:
                logger.exception(f"Unexpected error executing routine '{query}' with args {args}: {e}")
                raise



def parse_sql_statement(sql: str) -> Tuple[str, Tuple[Union[str, int, None], ...]]:
    """
    Parse a SQL query to handle both stored procedure calls ('CALL proc_name(...)')
    and regular SQL statements (e.g., 'DELETE FROM ...').

    Args:
        sql (str): The SQL query.

    Returns:
        Tuple[str, Tuple[Union[str, int, None], ...]]:
            - SQL query (with placeholders if needed).
            - Arguments as a tuple (empty for non-parameterized queries).
    """
    sql = sql.strip()
    if sql.upper().startswith("CALL"):
        match = re.match(r"CALL\s+(\w+)\((.*)\);", sql, re.IGNORECASE)
        if not match:
            raise ValueError(f"Invalid sql call statement: {sql}")

        procedure_name = match.group(1)
        args_string = match.group(2)
        raw_args = [arg.strip() for arg in args_string.split(",")] if args_string else []
        parsed_args = []
        for arg in raw_args:
            if arg.upper() == "NULL":
                parsed_args.append(None)
            elif re.match(r"^-?\d+(\.\d+)?$", arg):
                parsed_args.append(float(arg) if '.' in arg else int(arg))
            elif arg.startswith("'") and arg.endswith("'"):
                parsed_args.append(arg[1:-1])
            else:
                raise ValueError(f"Unrecognized argument: {arg}")

        placeholders = ", ".join(["%s"] * len(parsed_args))
        query = f"CALL {procedure_name}({placeholders});"
        return query, tuple(parsed_args)

    else:
        match = re.findall(r"%s", sql)
        if match:
            raise ValueError("Expected arguments to be supplied for parameterized query.")
        else:
            return sql, ()

def validate_message(message):
    """
    Validate the "message" field to ensure it is a string.
    If the field is not a string, convert it to a string or JSON representation.
    """
    if isinstance(message, str):
        return message
    elif isinstance(message, (dict, list)):
        try:
            return json.dumps(message, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Unable to JSON encode message: {message}. Error: {e}")
            return str(message)
    else:
        logger.warning(f"Invalid type for 'message': {type(message)}. Converting to string.")
        return str(message)

