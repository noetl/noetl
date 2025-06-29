import os
import json
import uuid
from typing import List
import psycopg
from noetl.common import setup_logger

logger = setup_logger(__name__, include_location=True)

class DatabaseSchema:

    def __init__(self, conn=None, pgdb: str = None):
        """
        Initialize the Database Schema.

        Args:
            conn: A database connection
            pgdb: Postgres connection string
        """
        self.conn = conn
        self.pgdb = pgdb
        self.is_postgres = False
        if self.conn is None:
            self.initialize_connection()

    def initialize_connection(self):
        try:
            if self.pgdb is None:
                self.pgdb = f"dbname={os.environ.get('POSTGRES_DB', 'noetl')} user={os.environ.get('POSTGRES_USER', 'noetl')} password={os.environ.get('POSTGRES_PASSWORD', 'noetl')} host={os.environ.get('POSTGRES_HOST', 'localhost')} port={os.environ.get('POSTGRES_PORT', '5434')}"
                logger.info(f"Using default Postgres connection string: {self.pgdb}")

            self.conn = psycopg.connect(self.pgdb)
            self.is_postgres = True
            logger.info("Connected to Postgres database.")
        except Exception as e:
            logger.error(f"Failed to connect to Postgres: {e}.")
            raise


    def init_database(self):
        try:
            logger.info("Initializing database tables.")
            self.test_connection()
            self.create_postgres_tables()
            tables = self.list_tables()
            logger.info(f"Tables in database: {tables}.")

            return True
        except Exception as e:
            logger.error(f"Error initializing database: {e}.", exc_info=True)
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
            logger.info("Creating resource table if it doesn't exist.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS resource (
                    name TEXT PRIMARY KEY
                )
            """)

            logger.info("Creating catalog table if it doesn't exist.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS catalog (
                    resource_path     TEXT     NOT NULL,
                    resource_type     TEXT     NOT NULL REFERENCES resource(name),
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

            logger.info("Creating workload table if it doesn't exist.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workload (
                    execution_id VARCHAR,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    data TEXT,
                    PRIMARY KEY (execution_id)
                )
            """)
            self.test_workload_table()

            logger.info("Creating event_log table.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS event_log (
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflow (
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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workbook (
                    execution_id VARCHAR,
                    task_id VARCHAR,
                    task_name VARCHAR,
                    task_type VARCHAR,
                    raw_config TEXT,
                    PRIMARY KEY (execution_id, task_id)
                )
            """)

            logger.info("Creating transition table.")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transition (
                    execution_id VARCHAR,
                    from_step VARCHAR,
                    to_step VARCHAR,
                    condition TEXT,
                    with_params TEXT,
                    PRIMARY KEY (execution_id, from_step, to_step, condition)
                )
            """)

            self.conn.commit()
            logger.info("PostgreSQL database tables initialized")


    def test_workload_table(self):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'workload'
                    )
                """)
                table_exists = cursor.fetchone()[0]
                if not table_exists:
                    logger.error("Failed to create workload table.")
                else:
                    logger.info("Workload table created.")

                    try:
                        test_id = f"test_{uuid.uuid4()}"
                        test_data = json.dumps({"test": "data"})
                        logger.info(f"Testing workload table with test_id: {test_id}")

                        cursor.execute("""
                            INSERT INTO workload (execution_id, data)
                            VALUES (%s, %s)
                            ON CONFLICT (execution_id) DO UPDATE
                            SET data = EXCLUDED.data
                        """, (test_id, test_data))
                        self.conn.commit()

                        cursor.execute("""
                            SELECT data FROM workload WHERE execution_id = %s
                        """, (test_id,))
                        row = cursor.fetchone()
                        if row and row[0] == test_data:
                            logger.info("Tested workload table insert and select.")
                        else:
                            logger.error(f"Failed to verify test data in workload table. Expected: {test_data}, Got: {row[0] if row else None}")

                        cursor.execute("""
                            DELETE FROM workload WHERE execution_id = %s
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
                    WHERE table_schema = 'public'
                """)
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
                        WHERE table_name = %s
                    )
                """, (table_name,))
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error checking if table exists: {e}.", exc_info=True)
            return False

    def close(self):
        if self.conn:
            try:
                self.conn.close()
                logger.info("Database connection closed.")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}.", exc_info=True)
