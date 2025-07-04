import os
import json
import uuid
from typing import List, Optional
import psycopg
from noetl.common import setup_logger

logger = setup_logger(__name__, include_location=True)

class DatabaseSchema:

    def __init__(self, conn=None, pgdb: str = None, admin_conn: str = None, noetl_user: str = None, noetl_password: str = None, noetl_schema: str = None, auto_setup: bool = False):
        """
        Initialize the Database Schema.

        Args:
            conn: A database connection (will be created if None)
            pgdb: Postgres connection string for noetl user
            admin_conn: Admin connection string for creating user/schema
            noetl_user: Username for noetl operations (will be determined from env vars if None)
            noetl_password: Password for noetl user (will be determined from env vars if None)
            noetl_schema: Schema name for noetl tables (will be determined from env vars if None)
            auto_setup: If True, automatically create user/schema during initialization (default: False)
        """
        self.conn = conn
        self.pgdb = pgdb
        self.admin_conn = admin_conn
        self.auto_setup = auto_setup
        self.is_postgres = False
        self.admin_connection = None

        self.set_noetl_credentials(noetl_user, noetl_password, noetl_schema)

        if self.conn is None:
            self.initialize_connection()

    def set_noetl_credentials(self, noetl_user: str = None, noetl_password: str = None, noetl_schema: str = None):
        self.noetl_user = noetl_user or os.environ.get('NOETL_USER', 'noetl')
        self.noetl_password = noetl_password or os.environ.get('NOETL_PASSWORD', 'noetl')
        self.noetl_schema = noetl_schema or os.environ.get('NOETL_SCHEMA', 'noetl')
        logger.info(f"Using admin credentials for setup, NoETL user: {self.noetl_user}, schema: {self.noetl_schema}")


    def initialize_connection(self):
        try:
            if self.admin_conn is None:
                postgres_user = os.environ.get('POSTGRES_USER')
                postgres_password = os.environ.get('POSTGRES_PASSWORD')
                db_name = os.environ.get('POSTGRES_DB', 'postgres')
                host = os.environ.get('POSTGRES_HOST', 'localhost')
                port = os.environ.get('POSTGRES_PORT', '5434')
                self.admin_conn = f"dbname={db_name} user={postgres_user} password={postgres_password} host={host} port={port}"
                logger.info(f"Using admin connection: dbname={db_name} user={postgres_user} host={host} port={port}")


            if self.pgdb is None:
                db_name = os.environ.get('POSTGRES_DB', 'postgres')
                host = os.environ.get('POSTGRES_HOST', 'localhost')
                port = os.environ.get('POSTGRES_PORT', '5434')

                self.pgdb = f"dbname={db_name} user={self.noetl_user} password={self.noetl_password} host={host} port={port}"
                logger.info(f"NoETL connection: dbname={db_name} user={self.noetl_user} host={host} port={port}")

            if self.auto_setup:
                self.create_noetl_schema()

            try:
                self.conn = psycopg.connect(self.pgdb)
                self.is_postgres = True
                logger.info("Connected to Postgres database as noetl user.")
            except psycopg.OperationalError as e:
                postgres_user = os.environ.get('POSTGRES_USER')
                postgres_password = os.environ.get('POSTGRES_PASSWORD')

                if postgres_user and postgres_password:
                    logger.info(f"NoETL user connection failed, attempting to create user/schema: {e}")
                    self.create_noetl_schema()
                    self.conn = psycopg.connect(self.pgdb)
                    self.is_postgres = True
                    logger.info("Connected to Postgres database as noetl user after creating infrastructure.")
                else:
                    raise

        except Exception as e:
            logger.error(f"Failed to connect to Postgres: {e}.")
            raise

    def create_noetl_metadata(self):
        try:
            logger.info("Verifying NoETL.")
            try:
                test_conn = psycopg.connect(self.pgdb)
                test_conn.close()
                logger.info("NoETL user connected.")

                self.conn = psycopg.connect(self.pgdb)
                with self.conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 1 FROM information_schema.schemata WHERE schema_name = %s
                    """, (self.noetl_schema,))

                    if cursor.fetchone():
                        logger.info(f"NoETL schema '{self.noetl_schema}' exists.")
                        return True
                    else:
                        logger.info(f"NoETL schema '{self.noetl_schema}' does not exist, trying to create new one.")
                        self.conn.close()
                        self.create_noetl_schema()
                        return True

            except psycopg.OperationalError as e:
                logger.info(f"NoETL user does not exist or cannot connect: {e}")
                logger.info("Creating NoETL user and schema.")
                self.create_noetl_schema()
                return True

        except Exception as e:
            logger.error(f"Error verifying/setting up NoETL infrastructure: {e}.", exc_info=True)
            raise

    def create_noetl_schema(self):
        try:
            logger.info("Setting up noetl user and schema.")
            self.admin_connection = psycopg.connect(self.admin_conn)

            with self.admin_connection.cursor() as cursor:
                cursor.execute("""
                    SELECT 1 FROM pg_roles WHERE rolname = %s
                """, (self.noetl_user,))

                if not cursor.fetchone():
                    logger.info(f"Creating user '{self.noetl_user}'...")
                    create_user_sql = f"""
                        CREATE USER {self.noetl_user} WITH 
                        PASSWORD '{self.noetl_password}'
                        CREATEDB
                        LOGIN
                    """
                    cursor.execute(create_user_sql)
                    logger.info(f"User '{self.noetl_user}' created successfully.")
                else:
                    logger.info(f"User '{self.noetl_user}' already exists.")

                cursor.execute("""
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = %s
                """, (self.noetl_schema,))

                if not cursor.fetchone():
                    logger.info(f"Creating schema '{self.noetl_schema}'.")
                    cursor.execute(f"CREATE SCHEMA {self.noetl_schema}")
                    logger.info(f"Schema '{self.noetl_schema}' created successfully.")
                else:
                    logger.info(f"Schema '{self.noetl_schema}' already exists.")

                logger.info(f"Granting permissions to user '{self.noetl_user}'.")
                cursor.execute(f"GRANT ALL PRIVILEGES ON SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                cursor.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                cursor.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {self.noetl_schema} GRANT ALL ON TABLES TO {self.noetl_user}")
                cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {self.noetl_schema} GRANT ALL ON SEQUENCES TO {self.noetl_user}")

                self.admin_connection.commit()
                logger.info("NoETL user and schema setup completed.")

        except Exception as e:
            logger.error(f"Error setting up noetl user and schema: {e}.", exc_info=True)
            if self.admin_connection:
                self.admin_connection.rollback()
            raise
        finally:
            if self.admin_connection:
                self.admin_connection.close()
                self.admin_connection = None

    def init_database(self):
        try:
            logger.info("Initializing database tables.")
            self.test_connection()
            self.set_search_path()
            self.create_postgres_tables()
            tables = self.list_tables()
            logger.info(f"Tables in noetl schema: {tables}.")

            return True
        except Exception as e:
            logger.error(f"Error initializing database: {e}.", exc_info=True)
            raise

    def set_search_path(self):
        """Set the search path to use the noetl schema"""
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(f"SET search_path TO {self.noetl_schema}, public")
                self.conn.commit()
                logger.info(f"Search path set to '{self.noetl_schema}, public'")
        except Exception as e:
            logger.error(f"Error setting search path: {e}.", exc_info=True)
            raise

    def test_connection(self):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    logger.info("Database connected.")
                else:
                    logger.error("Database connection test failed.")
        except Exception as e:
            logger.error(f"Error testing database connection: {e}.", exc_info=True)
            raise

    def create_postgres_tables(self):
        with self.conn.cursor() as cursor:
            logger.info("Creating resource table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.resource (
                    name TEXT PRIMARY KEY
                )
            """)

            logger.info("Creating catalog table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.catalog (
                    resource_path     TEXT     NOT NULL,
                    resource_type     TEXT     NOT NULL REFERENCES {self.noetl_schema}.resource(name),
                    resource_version  TEXT     NOT NULL,
                    source            TEXT     NOT NULL DEFAULT 'inline',
                    resource_location TEXT,
                    content           TEXT,
                    payload           JSONB    NOT NULL,
                    meta              JSONB,
                    template          TEXT,
                    timestamp         TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (resource_path, resource_version)
                )
            """)

            logger.info("Creating workload table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workload (
                    execution_id VARCHAR,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data TEXT,
                    PRIMARY KEY (execution_id)
                )
            """)
            self.test_workload_table()

            logger.info("Creating event_log table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.event_log (
                    execution_id VARCHAR,
                    event_id VARCHAR,
                    parent_event_id VARCHAR,
                    timestamp TIMESTAMP,
                    event_type VARCHAR,
                    node_id VARCHAR,
                    node_name VARCHAR,
                    node_type VARCHAR,
                    status VARCHAR,
                    duration DOUBLE PRECISION,
                    input_context TEXT,
                    output_result TEXT,
                    metadata TEXT,
                    error TEXT,
                    loop_id VARCHAR,
                    loop_name VARCHAR,
                    iterator VARCHAR,
                    items TEXT,
                    current_index INTEGER,
                    current_item TEXT,
                    results TEXT,
                    worker_id VARCHAR,
                    distributed_state VARCHAR,
                    context_key VARCHAR,
                    context_value TEXT,
                    PRIMARY KEY (execution_id, event_id)
                )
            """)

            logger.info("Creating workflow table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workflow (
                    execution_id VARCHAR,
                    step_id VARCHAR,
                    step_name VARCHAR,
                    step_type VARCHAR,
                    description TEXT,
                    raw_config TEXT,
                    PRIMARY KEY (execution_id, step_id)
                )
            """)

            logger.info("Creating workbook table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workbook (
                    execution_id VARCHAR,
                    task_id VARCHAR,
                    task_name VARCHAR,
                    task_type VARCHAR,
                    raw_config TEXT,
                    PRIMARY KEY (execution_id, task_id)
                )
            """)

            logger.info("Creating transition table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.transition (
                    execution_id VARCHAR,
                    from_step VARCHAR,
                    to_step VARCHAR,
                    condition TEXT,
                    with_params TEXT,
                    PRIMARY KEY (execution_id, from_step, to_step, condition)
                )
            """)

            self.conn.commit()
            logger.info("Postgres database tables initialized in noetl schema.")

    def test_workload_table(self):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'workload'
                    )
                """, (self.noetl_schema,))
                table_exists = cursor.fetchone()[0]
                if not table_exists:
                    logger.error("Failed to create workload table.")
                else:
                    logger.info("Workload table created.")

                    try:
                        test_id = f"test_{uuid.uuid4()}"
                        test_data = json.dumps({"test": "data"})
                        logger.info(f"Testing workload table with test_id: {test_id}.")

                        cursor.execute(f"""
                            INSERT INTO {self.noetl_schema}.workload (execution_id, data)
                            VALUES (%s, %s)
                            ON CONFLICT (execution_id) DO UPDATE
                            SET data = EXCLUDED.data
                        """, (test_id, test_data))
                        self.conn.commit()

                        cursor.execute(f"""
                            SELECT data FROM {self.noetl_schema}.workload WHERE execution_id = %s
                        """, (test_id,))
                        row = cursor.fetchone()
                        if row and row[0] == test_data:
                            logger.info("Tested workload table insert and select.")
                        else:
                            logger.error(f"Failed to verify test data in workload table. Expected: {test_data}, Got: {row[0] if row else None}")

                        cursor.execute(f"""
                            DELETE FROM {self.noetl_schema}.workload WHERE execution_id = %s
                        """, (test_id,))
                        self.conn.commit()
                        logger.info("Cleaned up test data from workload table.")
                    except Exception as e:
                        logger.error(f"Error testing workload table: {e}.", exc_info=True)
        except Exception as e:
            logger.error(f"Error testing workload table: {e}.", exc_info=True)

    def list_tables(self) -> List[str]:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                """, (self.noetl_schema,))
                return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.error(f"Error listing tables: {e}.", exc_info=True)
            return []

    def table_exists(self, table_name: str) -> bool:
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = %s
                    )
                """, (self.noetl_schema, table_name))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error checking if table exists: {e}.", exc_info=True)
            return False

    def drop_noetl_schema(self):
        """Drop the entire noetl schema and all its objects (use with caution)"""
        try:
            logger.warning(f"Dropping schema '{self.noetl_schema}' and all its objects.")
            self.admin_connection = psycopg.connect(self.admin_conn)

            with self.admin_connection.cursor() as cursor:
                cursor.execute(f"DROP SCHEMA IF EXISTS {self.noetl_schema} CASCADE")
                self.admin_connection.commit()
                logger.info(f"Schema '{self.noetl_schema}' dropped.")

        except Exception as e:
            logger.error(f"Error dropping schema: {e}.", exc_info=True)
            if self.admin_connection:
                self.admin_connection.rollback()
            raise
        finally:
            if self.admin_connection:
                self.admin_connection.close()
                self.admin_connection = None

    def close(self):
        if self.conn:
            try:
                self.conn.close()
                logger.info("Database connection closed.")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}.", exc_info=True)
