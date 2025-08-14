import os
import json
import uuid
import traceback
from typing import List, Optional, Dict, Any, Union
import psycopg
from noetl.common import make_serializable
from noetl.logger import setup_logger

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
        if noetl_schema is None and 'NOETL_SCHEMA' not in os.environ:
            error_msg = "NOETL_SCHEMA environment variable is required but not provided"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        self.noetl_user = noetl_user or os.environ.get('NOETL_USER')
        self.noetl_password = noetl_password or os.environ.get('NOETL_PASSWORD')
        self.noetl_schema = noetl_schema or os.environ.get('NOETL_SCHEMA')
        
        if not self.noetl_user:
            error_msg = "NOETL_USER environment variable is required but not provided"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        if not self.noetl_password:
            error_msg = "NOETL_PASSWORD environment variable is required but not provided"
            logger.error(error_msg)
            raise ValueError(error_msg)
            
        logger.info(f"Using NoETL credentials for setup, user: {self.noetl_user}, schema: {self.noetl_schema}")


    def initialize_connection(self):
        try:
            if self.admin_conn is None:
                if 'POSTGRES_USER' not in os.environ:
                    error_msg = "POSTGRES_USER environment variable is required but not provided"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                if 'POSTGRES_PASSWORD' not in os.environ:
                    error_msg = "POSTGRES_PASSWORD environment variable is required but not provided"
                    logger.error(error_msg)
                    raise ValueError(error_msg)
                
                postgres_user = os.environ.get('POSTGRES_USER')
                postgres_password = os.environ.get('POSTGRES_PASSWORD')
                db_name = os.environ.get('POSTGRES_DB')
                host = os.environ.get('POSTGRES_HOST')
                port = os.environ.get('POSTGRES_PORT')
                
                self.admin_conn = f"dbname={db_name} user={postgres_user} password={postgres_password} host={host} port={port} hostaddr='' gssencmode=disable"
                logger.info(f"Using admin connection: dbname={db_name} user={postgres_user} host={host} port={port}")


            if self.pgdb is None:
                db_name = os.environ.get('POSTGRES_DB')
                host = os.environ.get('POSTGRES_HOST')
                port = os.environ.get('POSTGRES_PORT')

                self.pgdb = f"dbname={db_name} user={self.noetl_user} password={self.noetl_password} host={host} port={port} hostaddr='' gssencmode=disable"
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

                logger.info(f"NoETL user connection failed, attempting to create user/schema: {e}")
                self.create_noetl_schema()
                try:
                    self.conn = psycopg.connect(self.pgdb)
                    self.is_postgres = True
                    logger.info("Connected to Postgres database as noetl user after creating infrastructure.")
                except Exception as conn_error:
                    logger.error(f"Failed to connect after schema creation: {conn_error}")
                    raise

        except Exception as e:
            logger.error(f"Failed to connect to Postgres: {e}.")
            raise

    def create_noetl_metadata(self):
        try:
            logger.info("SCHEMA VERIFICATION: Checking NoETL schema and user configuration")
            try:
                logger.info(f"SCHEMA VERIFICATION: Attempting to connect as NoETL user '{self.noetl_user}'")
                test_conn = psycopg.connect(self.pgdb)
                test_conn.close()
                logger.info(f"SCHEMA VERIFICATION: Successfully connected as NoETL user '{self.noetl_user}'")

                logger.info(f"SCHEMA VERIFICATION: Checking if schema '{self.noetl_schema}' exists")
                self.conn = psycopg.connect(self.pgdb)
                with self.conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT 1 FROM information_schema.schemata WHERE schema_name = %s
                    """, (self.noetl_schema,))

                    if cursor.fetchone():
                        logger.info(f"SCHEMA VERIFICATION: Schema '{self.noetl_schema}' exists")
                        return True
                    else:
                        logger.info(f"SCHEMA VERIFICATION: Schema '{self.noetl_schema}' does not exist")
                        logger.info(f"SCHEMA VERIFICATION: Will attempt to create schema '{self.noetl_schema}' using admin connection")
                        self.conn.close()
                        self.conn = None
                        self.create_noetl_schema()
                        return True

            except psycopg.OperationalError as e:
                logger.info(f"SCHEMA VERIFICATION: NoETL user '{self.noetl_user}' does not exist or cannot connect: {e}")
                logger.info(f"SCHEMA VERIFICATION: Will attempt to create user '{self.noetl_user}' and schema '{self.noetl_schema}'")
                self.create_noetl_schema()
                return True

        except Exception as e:
            logger.error(f"SCHEMA VERIFICATION FAILED: Error verifying/setting up NoETL infrastructure: {e}", exc_info=True)
            raise ValueError(f"Schema verification failed: {e}")

    def create_noetl_schema(self):
        try:
            logger.info(f"ATTEMPTING TO CREATE SCHEMA: Starting schema installation for '{self.noetl_schema}' with user '{self.noetl_user}'")
            logger.info(f"SCHEMA INSTALLATION: Using admin credentials to connect to database")
            try:
                self.admin_connection = psycopg.connect(self.admin_conn)
                logger.info("SCHEMA INSTALLATION: Successfully connected to database with admin credentials")
            except Exception as admin_conn_error:
                logger.error(f"SCHEMA INSTALLATION FAILED: Could not connect with admin credentials: {admin_conn_error}")
                logger.error("SCHEMA INSTALLATION FAILED: Make sure POSTGRES_USER and POSTGRES_PASSWORD environment variables are set correctly")
                raise

            with self.admin_connection.cursor() as cursor:
                logger.info(f"SCHEMA INSTALLATION: Checking if user '{self.noetl_user}' exists...")
                cursor.execute("""
                    SELECT 1 FROM pg_roles WHERE rolname = %s
                """, (self.noetl_user,))

                if not cursor.fetchone():
                    logger.info(f"SCHEMA INSTALLATION: Creating user '{self.noetl_user}'...")
                    create_user_sql = f"""
                        CREATE USER {self.noetl_user} WITH 
                        PASSWORD '{self.noetl_password}'
                        CREATEDB
                        LOGIN
                    """
                    cursor.execute(create_user_sql)
                    logger.info(f"SCHEMA INSTALLATION: User '{self.noetl_user}' created successfully")
                else:
                    logger.info(f"SCHEMA INSTALLATION: User '{self.noetl_user}' already exists")

                logger.info(f"SCHEMA INSTALLATION: Checking if schema '{self.noetl_schema}' exists...")
                cursor.execute("""
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = %s
                """, (self.noetl_schema,))

                if not cursor.fetchone():
                    logger.info(f"SCHEMA INSTALLATION: Creating schema '{self.noetl_schema}'...")
                    cursor.execute(f"CREATE SCHEMA {self.noetl_schema}")
                    logger.info(f"SCHEMA INSTALLATION: Schema '{self.noetl_schema}' created successfully")
                else:
                    logger.info(f"SCHEMA INSTALLATION: Schema '{self.noetl_schema}' already exists")

                logger.info(f"SCHEMA INSTALLATION: Granting permissions to user '{self.noetl_user}'...")
                cursor.execute(f"GRANT ALL PRIVILEGES ON SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                cursor.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                cursor.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {self.noetl_schema} GRANT ALL ON TABLES TO {self.noetl_user}")
                cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {self.noetl_schema} GRANT ALL ON SEQUENCES TO {self.noetl_user}")

                self.admin_connection.commit()
                logger.info("SCHEMA INSTALLATION: NoETL user and schema setup completed successfully")

        except Exception as e:
            logger.error(f"SCHEMA INSTALLATION FAILED: Error setting up noetl user and schema: {e}", exc_info=True)
            logger.error(f"SCHEMA INSTALLATION FAILED: Check that POSTGRES_USER has sufficient privileges to create users and schemas")
            logger.error(f"SCHEMA INSTALLATION FAILED: Verify that NOETL_USER, NOETL_PASSWORD, and NOETL_SCHEMA are correctly set")
            if self.admin_connection:
                self.admin_connection.rollback()
            raise ValueError(f"Schema installation failed: {e}")
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
            
            logger.info("Creating error_log table.")
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.error_log (
                    error_id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    error_type VARCHAR(50),
                    error_message TEXT,
                    execution_id VARCHAR,
                    step_id VARCHAR,
                    step_name VARCHAR,
                    template_string TEXT,
                    context_data JSONB,
                    stack_trace TEXT,
                    input_data JSONB,
                    output_data JSONB,
                    severity VARCHAR(20) DEFAULT 'error',
                    resolved BOOLEAN DEFAULT FALSE,
                    resolution_notes TEXT,
                    resolution_timestamp TIMESTAMP
                )
            """)
            
            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_error_log_timestamp ON {self.noetl_schema}.error_log (timestamp);
                CREATE INDEX IF NOT EXISTS idx_error_log_error_type ON {self.noetl_schema}.error_log (error_type);
                CREATE INDEX IF NOT EXISTS idx_error_log_execution_id ON {self.noetl_schema}.error_log (execution_id);
                CREATE INDEX IF NOT EXISTS idx_error_log_resolved ON {self.noetl_schema}.error_log (resolved);
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.noetl_schema}.credential (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL,
                    data_encrypted TEXT NOT NULL,
                    meta JSONB,
                    tags TEXT[],
                    description TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)

            cursor.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_credential_type ON {self.noetl_schema}.credential (type);
            """)
            
            try:
                cursor.execute(f"""
                    ALTER TABLE {self.noetl_schema}.catalog ADD COLUMN IF NOT EXISTS credential_id INTEGER;
                """)
            except Exception:
                pass

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
        """Drop the entire noetl schema and all its objects"""
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

    def log_error(self, 
                error_type: str, 
                error_message: str, 
                execution_id: str = None, 
                step_id: str = None, 
                step_name: str = None,
                template_string: str = None, 
                context_data: Dict = None, 
                stack_trace: str = None, 
                input_data: Any = None, 
                output_data: Any = None,
                severity: str = "error") -> Optional[int]:
        """
        Log an error to the error_log table.
        
        Args:
            error_type: The type of error (e.g., "template_rendering", "sql_rendering")
            error_message: The error message
            execution_id: The ID of the execution where the error occurred
            step_id: The ID of the step where the error occurred
            step_name: The name of the step where the error occurred
            template_string: The template that failed to render
            context_data: The context data used for rendering
            stack_trace: The stack trace of the error
            input_data: The input data related to the error
            output_data: The output data related to the error
            severity: The severity of the error (default: "error")
            
        Returns:
            The error_id of the inserted record, or None if insertion failed
        """
        try:
            if stack_trace is None and error_type == "template_rendering":
                stack_trace = ''.join(traceback.format_stack())
            
            context_data_json = json.dumps(make_serializable(context_data)) if context_data else None
            input_data_json = json.dumps(make_serializable(input_data)) if input_data else None
            output_data_json = json.dumps(make_serializable(output_data)) if output_data else None
            
            if not self.conn or self.conn.closed:
                self.initialize_connection()
                
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    INSERT INTO {self.noetl_schema}.error_log (
                        error_type, error_message, execution_id, step_id, step_name,
                        template_string, context_data, stack_trace, input_data, output_data, severity
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s::jsonb, %s
                    ) RETURNING error_id
                """, (
                    error_type, error_message, execution_id, step_id, step_name,
                    template_string, context_data_json, stack_trace, input_data_json, output_data_json, severity
                ))
                
                error_id = cursor.fetchone()[0]
                self.conn.commit()
                logger.info(f"Logged error to error_log table with error_id: {error_id}")
                return error_id
                
        except Exception as e:
            logger.error(f"Failed to log error to error_log table: {e}", exc_info=True)
            if self.conn:
                try:
                    self.conn.rollback()
                except:
                    pass
            return None
    
    def mark_error_resolved(self, error_id: int, resolution_notes: str = None) -> bool:
        """
        Mark an error as resolved in the error_log table.
        
        Args:
            error_id: The ID of the error to mark as resolved
            resolution_notes: Notes on how the error was resolved
            
        Returns:
            True if the error was marked as resolved, False otherwise
        """
        try:
            if not self.conn or self.conn.closed:
                self.initialize_connection()
                
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    UPDATE {self.noetl_schema}.error_log
                    SET resolved = TRUE, 
                        resolution_notes = %s,
                        resolution_timestamp = CURRENT_TIMESTAMP
                    WHERE error_id = %s
                """, (resolution_notes, error_id))
                
                self.conn.commit()
                logger.info(f"Marked error with error_id {error_id} as resolved")
                return True
                
        except Exception as e:
            logger.error(f"Failed to mark error as resolved: {e}", exc_info=True)
            if self.conn:
                try:
                    self.conn.rollback()
                except:
                    pass
            return False
    
    def get_errors(self, 
                  error_type: str = None, 
                  execution_id: str = None, 
                  resolved: bool = None, 
                  limit: int = 100, 
                  offset: int = 0) -> List[Dict]:
        """
        Get errors from the error_log table with optional filtering.
        
        Args:
            error_type: Filter by error type
            execution_id: Filter by execution ID
            resolved: Filter by resolved status
            limit: Maximum number of errors to return
            offset: Offset for pagination
            
        Returns:
            A list of error records as dictionaries
        """
        try:
            if not self.conn or self.conn.closed:
                self.initialize_connection()
                
            query = f"SELECT * FROM {self.noetl_schema}.error_log WHERE 1=1"
            params = []
            
            if error_type:
                query += " AND error_type = %s"
                params.append(error_type)
                
            if execution_id:
                query += " AND execution_id = %s"
                params.append(execution_id)
                
            if resolved is not None:
                query += " AND resolved = %s"
                params.append(resolved)
                
            query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            with self.conn.cursor() as cursor:
                cursor.execute(query, params)
                columns = [desc[0] for desc in cursor.description]
                errors = []
                
                for row in cursor.fetchall():
                    error_dict = dict(zip(columns, row))
                    
                    for field in ['context_data', 'input_data', 'output_data']:
                        if error_dict.get(field) and isinstance(error_dict[field], str):
                            try:
                                error_dict[field] = json.loads(error_dict[field])
                            except:
                                pass
                    
                    errors.append(error_dict)
                
                return errors
                
        except Exception as e:
            logger.error(f"Failed to get errors from error_log table: {e}", exc_info=True)
            return []
    
    def close(self):
        if self.conn:
            try:
                self.conn.close()
                logger.info("Database connection closed.")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}.", exc_info=True)
