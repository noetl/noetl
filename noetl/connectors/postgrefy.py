import asyncio
import contextlib
import json
import re
from typing import Any, Optional, Union, Sequence, Tuple
from psycopg_pool import AsyncConnectionPool, PoolTimeout
from psycopg.rows import dict_row
import psycopg
from psycopg.errors import (
    ForeignKeyViolation,
    UniqueViolation,
    NotNullViolation,
    IntegrityError,
)
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel
from noetl.util import setup_logger
from noetl.api.models.noetl_init import seed_default_types

logger = setup_logger(__name__, include_location=True)

class PostgresHandler:
    def __init__(self, config):
        self.config = config
        self.pool: Optional[AsyncConnectionPool] = None
        self.pool_lock = asyncio.Lock()
        self._initialized = False
        self.engine = None
        self.session_maker = None

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
                        self.config.connection_uri(),
                        min_size=self.config.postgres_pool_min_size,
                        max_size=self.config.postgres_pool_max_size,
                        timeout=self.config.postgres_pool_timeout,
                        open=False
                    )
                    await self.pool.open()
                    logger.success("Postgres connection pool initialized.")
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


    @contextlib.asynccontextmanager
    async def get_session(self) -> AsyncSession:
        async_session = sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)
        async with async_session() as session:
            yield session

    async def initialize_sqlmodel(self):
        if self.engine is None:
            self.engine = create_async_engine(self.config.sqlalchemy_uri(), future=True, echo=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
            logger.success("NoETL tables created.")
        async with self.get_session() as session:
            await seed_default_types(session)
            logger.success("NoETL default types seeded.")

    async def create_partitions(self, sql_statements: list[str] = None):
        """
        Create partitions for the table by range:
        sql_statements = [
        'CREATE TABLE IF NOT EXISTS event_2025_04 PARTITION OF event FOR VALUES FROM ('2025-04-01') TO ('2025-05-01');',
        'CREATE TABLE IF NOT EXISTS event_2025_04 PARTITION OF event FOR VALUES FROM ('2025-05-01') TO ('2025-06-01');'
        ]
        """
        async with self.connect() as conn:
            for statement in sql_statements:
                try:
                    await conn.execute(statement)
                    logger.info(f"Partition created using query: {statement}.")
                except Exception as e:
                    logger.error(f"Error creating partition with query: {statement}. Error: {e}.")

    async def execute(
            self,
            query: str,
            args: Union[Sequence[Any], tuple, list] = (),
            fetch: bool = True,
            connection_string: Optional[str] = None,
    ) -> Optional[list[dict]]:
        if len(args) == 1 and isinstance(args[0], (tuple, list)):
            args = args[0]
        query_type = re.match(r'^\s*(\w+)', query)
        if query_type:
            keyword = query_type.group(1).upper()
            if keyword == "CALL" and fetch:
                logger.warning("Fetch disabled.")
                fetch = False

        if connection_string:
            conn = psycopg.connect(connection_string)
            try:
                with conn.cursor() as cur:
                    logger.debug(f"Executing: {query} | Args: {args}")
                    cur.execute(query, args)
                    if fetch and cur.description:
                        return cur.fetchall()
                    conn.commit()
                    return None
            except Exception as e:
                logger.error(f"Failed to connect database {connection_string}: {e}")
                raise

        if not self.pool:
            logger.error("Connection pool is not initialized.")
            return None

        async with self.connect() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                try:
                    logger.debug(f"Executing query: {query} | Args: {args}")
                    await cur.execute(query, args)
                    await conn.commit()
                    if fetch and cur.description:
                        return await cur.fetchall()
                    logger.success(f"Executed: {query}")
                    return None
                except ForeignKeyViolation as e:
                    logger.error(f"Foreign Key Violation: {e}")
                    raise
                except UniqueViolation as e:
                    logger.error(f"Unique Constraint Violation: {e}")
                    raise
                except NotNullViolation as e:
                    logger.error(f"Not Null Constraint Violation: {e}")
                    raise
                except IntegrityError as e:
                    logger.error(f"Integrity Error: {e}")
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error executing SQL: {e}")
                    raise

    async def routine(self, query: str, args: Tuple = (), is_procedure: bool = False, fetch_all: bool = True):
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



def parse_sql(sql: str) -> Tuple[str, Tuple[Union[str, int, None], ...]]:
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
            raise ValueError("Expected arguments in parameterized query.")
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
        logger.warning(f"Invalid message type: {type(message)}. Trying convert to string.")
        return str(message)
