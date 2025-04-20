import asyncio
import contextlib
import json
import re
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
import psycopg
from noetl.shared import setup_logger
logger = setup_logger(__name__, include_location=True)

def pgsql_execute(query: str, params=None, *, user="noetl", password="noetl", host="localhost", port=5432, database="noetl"):
    conn = psycopg.connect(
        user=user,
        password=password,
        host=host,
        port=port,
        database=database
    )
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                return cur.fetchall()
            conn.commit()
    finally:
        conn.close()

class PostgresHandler:
    def __init__(self, config):
        self.config = config
        self.pool: Optional[AsyncConnectionPool] = None
        self.pool_lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            logger.debug("Postgres handler already initialized.")
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
                logger.error(f"Unexpected error during initialization: {e}.")
                if attempt == 2:
                    raise

    async def initialize_pool(self):
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
                    logger.info("Postgres connection pool initialized.")
                except Exception as e:
                    logger.error(f"Error initializing database connection pool: {e}.")
                    raise

    @contextlib.asynccontextmanager
    async def connect(self):
        if not self.pool:
            await self.initialize_pool()

        for attempt in range(3):
            try:
                async with self.pool.connection() as conn:
                    if self.config.timezone:
                        await conn.execute(f"SET TIME ZONE '{self.config.timezone}'")
                    yield conn
                    return
            except PoolTimeout as e:
                logger.warning(f"Connection timeout: {e}. Retrying.")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Error acquiring connection: {e}.")
                if attempt == 2:
                    raise
            finally:
                logger.debug("Closing database connection generator.")

    async def execute_query(self, query: str, *args):
        """Execute database query."""
        async with self.connect() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                try:
                    logger.debug(f"Executing database query: {query} | Args: {args}.")
                    await cur.execute(query, args)
                    conn.commit()
                    if cur.description:
                        return await cur.fetchall()
                except ForeignKeyViolation as e:
                    logger.error(f"Foreign Key Violation: {e}.")
                    raise e
                except UniqueViolation as e:
                    logger.error(f"Unique Constraint Violation: {e}.")
                    raise e
                except NotNullViolation as e:
                    logger.error(f"Not Null Constraint Violation: {e}.")
                    raise e
                except IntegrityError as e:
                    logger.error(f"Integrity Error: {e}.")
                    raise e
                except Exception as e:
                    logger.error(f"Unexpected error executing database query: {e}.")
                    raise e
                finally:
                    conn.putconn(conn)

    async def execute_sql(self, query: str, args: Tuple = ()):
        if not self.pool:
            logger.error("Connection pool is not initialized.")
            return None

        async with self.connect() as conn:
            try:
                async with conn.cursor(row_factory=dict_row) as cur:
                    logger.debug(f"Execute: {query} with args: {args}.")
                    await cur.execute(query, args)
                    conn.commit()
                    logger.success(f"Command executed: {query}.")
                    return None
            except Exception as e:
                logger.error(f"Error executing sql statement '{query}': {e}.")
                raise e
            finally:
                conn.putconn(conn)

    async def call_routine(self, query: str, args: Tuple = (), is_procedure: bool = False, fetch_all: bool = True):
        if not self.pool:
            logger.error("Connection pool is not initialized.")
            return None

        async with self.connect() as conn:
            try:
                async with conn.cursor(row_factory=dict_row) as cur:
                    if is_procedure:
                        procedure_call = f"CALL {query}({', '.join(['%s'] * len(args))})"
                        logger.debug(f"Calling routine: {procedure_call} with args: {args}.")
                        await cur.execute(procedure_call, args)
                        logger.success(f"Routine '{query}' executed.")
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
                logger.error(f"Foreign Key Violation: {e}.")
                raise
            except UniqueViolation as e:
                logger.error(f"Unique Constraint Violation: {e}.")
                raise
            except NotNullViolation as e:
                logger.error(f"Not Null Constraint Violation: {e}.")
                raise
            except IntegrityError as e:
                logger.error(f"Integrity Error: {e}.")
                raise
            except Exception as e:
                logger.exception(f"Unexpected error while executing routine '{query}' with args {args}: {e}.")
                raise



def parse_sql_statement(sql: str) -> Tuple[str, Tuple[Union[str, int, None], ...]]:
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
                raise ValueError(f"Unrecognized argument: {arg}.")

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
    if isinstance(message, str):
        return message
    elif isinstance(message, (dict, list)):
        try:
            return json.dumps(message, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Unable to encode message: {message}. Error: {e}.")
            return str(message)
    else:
        logger.warning(f"Invalid type for 'message': {type(message)}. Converting to string.")
        return str(message)

