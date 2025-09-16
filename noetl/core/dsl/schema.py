import os
import sys
import json
import uuid
import traceback
import datetime
from typing import List, Optional, Dict, Any, Union
import psycopg
from noetl.core.common import make_serializable, get_snowflake_id
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

class DatabaseSchema:

    def __init__(self, conn=None, pgdb: str = None, admin_conn: str = None, noetl_user: str = None, noetl_password: str = None, noetl_schema: str = None, auto_setup: bool = False):
        """
        Initialize the Database Schema.

        Args:
            conn: A database connection (will be created if None)
            pgdb: Postgres connection string for noetl user
            admin_conn: Admin connection string for creating user/schema
            noetl_user: Username for noetl operations (will be determined from config if None)
            noetl_password: Password for noetl user (will be determined from config if None)
            noetl_schema: Schema name for noetl tables (will be determined from config if None)
            auto_setup: If True, automatically create user/schema during initialization (default: False)
        """
        self.conn = conn
        self.pgdb = pgdb
        self.admin_conn = admin_conn
        self.auto_setup = auto_setup
        self.is_postgres = False
        self.admin_connection = None

        try:
            from noetl.core.config import get_settings
            self.settings = get_settings()
            self.set_noetl_credentials(noetl_user, noetl_password, noetl_schema)
        except Exception as e:
            logger.error(f"FATAL: Failed to initialize database schema: {e}")
            logger.error("FATAL: Exiting immediately due to configuration error")
            sys.exit(1)

    async def initialize_async(self):
        """Async initialization method that must be called after __init__"""
        try:
            if self.conn is None:
                await self.initialize_connection()
        except Exception as e:
            logger.error(f"FATAL: Failed to initialize async database connection: {e}")
            logger.error("FATAL: Exiting immediately due to database connection failure")
            sys.exit(1)

    def set_noetl_credentials(self, noetl_user: str = None, noetl_password: str = None, noetl_schema: str = None):
        self.noetl_user = noetl_user or self.settings.noetl_user
        self.noetl_password = noetl_password or self.settings.noetl_password
        self.noetl_schema = noetl_schema or self.settings.noetl_schema

        logger.info(f"Using NoETL credentials for setup, user: {self.noetl_user}, schema: {self.noetl_schema}")


    async def initialize_connection(self):
        try:
            if self.admin_conn is None:
                self.admin_conn = self.settings.admin_conn_string
                logger.info(f"Using admin connection: dbname={self.settings.postgres_db} user={self.settings.postgres_user} host={self.settings.postgres_host} port={self.settings.postgres_port}")

            if self.pgdb is None:
                self.pgdb = self.settings.noetl_conn_string
                logger.info(f"NoETL async connection: dbname={self.settings.postgres_db} user={self.noetl_user} host={self.settings.postgres_host} port={self.settings.postgres_port}")

            if self.auto_setup:
                if getattr(self, "settings", None) and getattr(self.settings, "noetl_drop_schema", False):
                    await self.drop_noetl_schema_async()
                await self.create_noetl_schema()

            try:
                self.conn = await psycopg.AsyncConnection.connect(self.pgdb)
                await self.conn.set_autocommit(True)
                self.is_postgres = True
                logger.info("Connected to Postgres database as noetl user (async).")
            except psycopg.OperationalError as e:
                logger.error(f"NoETL user async connection failed, attempting to create user/schema: {e}")
                await self.create_noetl_schema()
                try:
                    self.conn = await psycopg.AsyncConnection.connect(self.pgdb)
                    await self.conn.set_autocommit(True)
                    self.is_postgres = True
                    logger.info("Connected to Postgres database as noetl user after creating infrastructure (async).")
                except Exception as conn_error:
                    logger.error(f"FATAL: Failed to connect after schema creation: {conn_error}")
                    raise

        except Exception as e:
            logger.error(f"FATAL: Failed to establish async connection to Postgres: {e}")
            raise


    def initialize_connection_sync(self):
        try:
            if self.admin_conn is None:
                self.admin_conn = self.settings.admin_conn_string
                logger.info(f"Using admin connection: dbname={self.settings.postgres_db} user={self.settings.postgres_user} host={self.settings.postgres_host} port={self.settings.postgres_port}")

            if self.pgdb is None:
                self.pgdb = self.settings.noetl_conn_string
                logger.info(f"NoETL sync connection: dbname={self.settings.postgres_db} user={self.noetl_user} host={self.settings.postgres_host} port={self.settings.postgres_port}")

            if self.auto_setup and (self.conn is None):
                try:
                    self.conn = psycopg.connect(self.pgdb)
                    self.conn.autocommit = True
                    self.is_postgres = True
                    logger.info("Connected to Postgres database as noetl user (sync).")
                except Exception as e:
                    logger.warning(f"NoETL user sync connection failed, attempting to create user/schema: {e}")
                    try:
                        admin = psycopg.connect(self.admin_conn)
                        try:
                            admin.autocommit = True
                            with admin.cursor() as ac:
                                ac.execute("""
                                    DO $$
                                    BEGIN
                                        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) THEN
                                            EXECUTE format('CREATE USER %s WITH PASSWORD %L CREATEDB LOGIN', %s, %s, %s);
                                        END IF;
                                    END $$;
                                """, (self.noetl_user, self.noetl_user, self.noetl_password, self.noetl_user))
                                ac.execute("""
                                    DO $$
                                    BEGIN
                                        IF NOT EXISTS (
                                            SELECT 1 FROM information_schema.schemata WHERE schema_name = %s
                                        ) THEN
                                            EXECUTE format('CREATE SCHEMA %I', %s);
                                        END IF;
                                    END $$;
                                """, (self.noetl_schema, self.noetl_schema))
                                try:
                                    ac.execute(f"GRANT ALL PRIVILEGES ON SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                                except Exception:
                                    pass
                        finally:
                            admin.close()
                        self.conn = psycopg.connect(self.pgdb)
                        self.conn.autocommit = True
                        self.is_postgres = True
                        logger.info("Connected to Postgres database as noetl user after creating infrastructure (sync).")
                    except Exception as conn_error:
                        logger.error(f"FATAL: Failed to connect after schema creation (sync): {conn_error}")
                        raise
            else:
                if self.conn is None:
                    self.conn = psycopg.connect(self.pgdb)
                    self.conn.autocommit = True
                    self.is_postgres = True
                    logger.info("Connected to Postgres database as noetl user (sync).")
        except Exception as e:
            logger.error(f"FATAL: Failed to establish sync connection to Postgres: {e}")
            raise

    def test_connection_sync(self):
        try:
            if self.conn is None:
                logger.error("FATAL: Database connection is None. Connection was not established properly (sync).")
                raise ValueError("Database connection is None")
            with self.conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if not (result and result[0] == 1):
                    raise ValueError("Database connection test failed (sync)")
                logger.info("Database connected (sync).")
        except Exception as e:
            logger.error(f"FATAL: Error testing database connection (sync): {e}.", exc_info=True)
            raise

    def set_search_path_sync(self):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(f"SET search_path TO {self.noetl_schema}, public")
                if not getattr(self.conn, "autocommit", False):
                    self.conn.commit()
                logger.info(f"Search path set to '{self.noetl_schema}, public' (sync)")
        except Exception as e:
            logger.error(f"Error setting search path (sync): {e}.", exc_info=True)
            raise

    def create_postgres_tables_sync(self):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.resource (
                        name TEXT PRIMARY KEY
                    )
                """)
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
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workload (
                        execution_id BIGINT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        data TEXT,
                        PRIMARY KEY (execution_id)
                    )
                """)
                # Create unified event table (renamed from event_log) with optional stack_trace column
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.event (
                        execution_id BIGINT,
                        event_id BIGINT,
                        parent_event_id BIGINT,
                        parent_execution_id BIGINT,
                        timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        event_type VARCHAR,
                        node_id VARCHAR,
                        node_name VARCHAR,
                        node_type VARCHAR,
                        status VARCHAR,
                        duration DOUBLE PRECISION,
                        context TEXT,
                        result TEXT,
                        metadata TEXT,
                        error TEXT,
                        loop_id VARCHAR,
                        loop_name VARCHAR,
                        iterator VARCHAR,
                        items TEXT,
                        current_index INTEGER,
                        current_item TEXT,
                        worker_id VARCHAR,
                        distributed_state VARCHAR,
                        context_key VARCHAR,
                        context_value TEXT,
                        trace_component JSONB,
                        stack_trace TEXT,
                        PRIMARY KEY (execution_id, event_id)
                    )
                """)
                # Back-compat: if event_log table exists but event does not, try to rename event_log -> event
                try:
                    cursor.execute(f"SELECT to_regclass('{self.noetl_schema}.event') IS NOT NULL")
                    ev_exists = (cursor.fetchone() or [False])[0]
                    cursor.execute(f"SELECT to_regclass('{self.noetl_schema}.event_log') IS NOT NULL")
                    evlog_exists = (cursor.fetchone() or [False])[0]
                    if (not ev_exists) and evlog_exists:
                        cursor.execute(f"ALTER TABLE {self.noetl_schema}.event_log RENAME TO event")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                # Ensure helper columns exist
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS trace_component JSONB")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS parent_execution_id BIGINT")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS stack_trace TEXT")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                # Create back-compat view event_log -> event
                try:
                    cursor.execute(f"CREATE OR REPLACE VIEW {self.noetl_schema}.event_log AS SELECT * FROM {self.noetl_schema}.event")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workflow (
                        execution_id BIGINT,
                        step_id VARCHAR,
                        step_name VARCHAR,
                        step_type VARCHAR,
                        description TEXT,
                        raw_config TEXT,
                        PRIMARY KEY (execution_id, step_id)
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workbook (
                        execution_id BIGINT,
                        task_id VARCHAR,
                        task_name VARCHAR,
                        task_type VARCHAR,
                        raw_config TEXT,
                        PRIMARY KEY (execution_id, task_id)
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.transition (
                        execution_id BIGINT,
                        from_step VARCHAR,
                        to_step VARCHAR,
                        condition TEXT,
                        with_params TEXT,
                        PRIMARY KEY (execution_id, from_step, to_step, condition)
                    )
                """)
                # Remove legacy error_log table if present (after best-effort migration)
                try:
                    # Migrate a subset of error_log into event as error events if both exist
                    cursor.execute(f"SELECT to_regclass('{self.noetl_schema}.error_log') IS NOT NULL")
                    err_exists = (cursor.fetchone() or [False])[0]
                    if err_exists:
                        try:
                            cursor.execute(f"""
                                INSERT INTO {self.noetl_schema}.event (
                                    execution_id, event_id, timestamp, event_type, node_id, node_name, status,
                                    context, result, metadata, error, stack_trace
                                )
                                SELECT 
                                    COALESCE(execution_id, 0) as execution_id,
                                    error_id as event_id,
                                    COALESCE(timestamp, CURRENT_TIMESTAMP) as timestamp,
                                    'error' as event_type,
                                    step_id as node_id,
                                    step_name as node_name,
                                    'FAILED' as status,
                                    context_data::text as context,
                                    output_data::text as result,
                                    json_build_object(
                                        'error_type', error_type,
                                        'severity', severity,
                                        'resolved', resolved,
                                        'resolution_notes', resolution_notes,
                                        'template_string', template_string
                                    )::text as metadata,
                                    error_message as error,
                                    stack_trace as stack_trace
                                FROM {self.noetl_schema}.error_log
                                ON CONFLICT (execution_id, event_id) DO NOTHING
                            """)
                        except Exception:
                            if not getattr(self.conn, "autocommit", False):
                                self.conn.rollback()
                        try:
                            cursor.execute(f"DROP TABLE IF EXISTS {self.noetl_schema}.error_log CASCADE")
                        except Exception:
                            if not getattr(self.conn, "autocommit", False):
                                self.conn.rollback()
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
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
                # Ensure ownership so subsequent index/alter operations succeed
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.credential OWNER TO {self.noetl_user}")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                    try:
                        admin = psycopg.connect(self.admin_conn)
                        try:
                            admin.autocommit = True
                            with admin.cursor() as ac:
                                ac.execute(f"ALTER TABLE {self.noetl_schema}.credential OWNER TO {self.noetl_user}")
                        finally:
                            admin.close()
                    except Exception:
                        pass
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_credential_type ON {self.noetl_schema}.credential (type);
                """)
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.catalog ADD COLUMN IF NOT EXISTS credential_id INTEGER;")
                except Exception:
                    pass
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.runtime (
                        runtime_id BIGINT PRIMARY KEY,
                        name TEXT NOT NULL,
                        component_type TEXT NOT NULL CHECK (component_type IN ('worker_pool','server_api','broker')),
                        base_url TEXT,
                        status TEXT NOT NULL,
                        labels JSONB,
                        capabilities JSONB,
                        capacity INTEGER,
                        runtime JSONB,
                        last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.runtime OWNER TO {self.noetl_user}")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                    try:
                        admin = psycopg.connect(self.admin_conn)
                        try:
                            admin.autocommit = True
                            with admin.cursor() as ac:
                                ac.execute(f"ALTER TABLE {self.noetl_schema}.runtime OWNER TO {self.noetl_user}")
                        finally:
                            admin.close()
                    except Exception:
                        pass
                # Schedule registry for time-based playbook execution
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.schedule (
                        schedule_id BIGSERIAL PRIMARY KEY,
                        playbook_path TEXT NOT NULL,
                        playbook_version TEXT,
                        cron TEXT,                 -- standard 5-field (or 6) cron expression OR NULL if using interval
                        interval_seconds INTEGER,  -- alternative to cron; if set > 0 used when cron is NULL
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        timezone TEXT DEFAULT 'UTC',
                        next_run_at TIMESTAMPTZ,   -- cached next run timestamp
                        last_run_at TIMESTAMPTZ,
                        last_status TEXT,
                        input_payload JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        meta JSONB
                    )
                """)
                # Ensure ownership for schedule table before creating indexes
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.schedule OWNER TO {self.noetl_user}")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                    try:
                        admin = psycopg.connect(self.admin_conn)
                        try:
                            admin.autocommit = True
                            with admin.cursor() as ac:
                                ac.execute(f"ALTER TABLE {self.noetl_schema}.schedule OWNER TO {self.noetl_user}")
                        finally:
                            admin.close()
                    except Exception:
                        pass
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_schedule_next_run ON {self.noetl_schema}.schedule (next_run_at) WHERE enabled = TRUE;
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_schedule_playbook ON {self.noetl_schema}.schedule (playbook_path);
                """)
                cursor.execute(f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_component_name ON {self.noetl_schema}.runtime (component_type, name);
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_runtime_type ON {self.noetl_schema}.runtime (component_type);
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_runtime_status ON {self.noetl_schema}.runtime (status);
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_runtime_runtime_type ON {self.noetl_schema}.runtime ((runtime->>'type'));
                """)
                # Queue table (work dispatch)
                queue_sql = f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.queue (
                        id BIGSERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ DEFAULT now(),
                        available_at TIMESTAMPTZ DEFAULT now(),
                        lease_until TIMESTAMPTZ,
                        last_heartbeat TIMESTAMPTZ,
                        status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','leased','done','failed','dead')),
                        execution_id BIGINT NOT NULL,
                        node_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        context JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        priority INT NOT NULL DEFAULT 0,
                        attempts INT NOT NULL DEFAULT 0,
                        max_attempts INT NOT NULL DEFAULT 5,
                        worker_id TEXT
                    )
                """
                cursor.execute(queue_sql)
                try:
                    cursor.execute(f"ALTER TABLE {self.noetl_schema}.queue OWNER TO {self.noetl_user}")
                except Exception:
                    if not getattr(self.conn, "autocommit", False):
                        self.conn.rollback()
                    # Try with admin connection if current user isn't the owner
                    try:
                        admin = psycopg.connect(self.admin_conn)
                        try:
                            admin.autocommit = True
                            with admin.cursor() as ac:
                                ac.execute(f"ALTER TABLE {self.noetl_schema}.queue OWNER TO {self.noetl_user}")
                        finally:
                            admin.close()
                    except Exception:
                        pass
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_status_available ON {self.noetl_schema}.queue (status, available_at, priority DESC, id)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_exec ON {self.noetl_schema}.queue (execution_id)
                """)
                try:
                    cursor.execute(f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_exec_node ON {self.noetl_schema}.queue (execution_id, node_id)
                    """)
                except Exception as e:
                    logger.warning(f"Skipping unique index creation idx_queue_exec_node (possible duplicates present): {e}")
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_worker ON {self.noetl_schema}.queue (worker_id)
                """)
                cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_lease_until ON {self.noetl_schema}.queue (lease_until)
                """)
                # ===== Identity & Collaboration Tables =====
                
                # 1.	Snowflake IDs for all tables → globally unique.
                # 2.	Profile table can be human or bot.
                # 3.	Session table tracks active connections.
                # 4.	Label hierarchy supports recursive namespaces/folders.
                # 5.	Chats live in labels, messages live in chats.
                # 6.	Members manage chat participants with roles (owner/admin/member).
                # 7.	Attachments can be linked to either chats or labels.
                
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.role (
                        id BIGINT PRIMARY KEY,
                        name TEXT UNIQUE NOT NULL,
                        description TEXT
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.profile (
                        id BIGINT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        email TEXT UNIQUE,
                        password_hash TEXT,
                        role_id BIGINT REFERENCES {self.noetl_schema}.role(id),
                        type TEXT NOT NULL CHECK (type IN ('user','bot')),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.session (
                        id BIGINT PRIMARY KEY,
                        profile_id BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        session_type TEXT NOT NULL CHECK (session_type IN ('user','bot','ai')),
                        connected_at TIMESTAMPTZ DEFAULT now(),
                        disconnected_at TIMESTAMPTZ,
                        metadata JSONB
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.label (
                        id BIGINT PRIMARY KEY,
                        parent_id BIGINT REFERENCES {self.noetl_schema}.label(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        owner_id BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.chat (
                        id BIGINT PRIMARY KEY,
                        label_id BIGINT REFERENCES {self.noetl_schema}.label(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        owner_id BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.member (
                        id BIGINT PRIMARY KEY,
                        chat_id BIGINT REFERENCES {self.noetl_schema}.chat(id) ON DELETE CASCADE,
                        profile_id BIGINT REFERENCES {self.noetl_schema}.profile(id) ON DELETE CASCADE,
                        role TEXT NOT NULL CHECK (role IN ('owner','admin','member')),
                        joined_at TIMESTAMPTZ DEFAULT now(),
                        UNIQUE(chat_id, profile_id)
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.message (
                        id BIGINT PRIMARY KEY,
                        chat_id BIGINT REFERENCES {self.noetl_schema}.chat(id) ON DELETE CASCADE,
                        sender_type TEXT NOT NULL CHECK (sender_type IN ('user','bot','ai','system')),
                        sender_id BIGINT,
                        role TEXT,
                        content TEXT NOT NULL,
                        metadata JSONB,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.attachment (
                        id BIGINT PRIMARY KEY,
                        label_id BIGINT REFERENCES {self.noetl_schema}.label(id) ON DELETE CASCADE,
                        chat_id BIGINT REFERENCES {self.noetl_schema}.chat(id) ON DELETE CASCADE,
                        filename TEXT NOT NULL,
                        filepath TEXT NOT NULL,
                        uploaded_by BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                try:
                    cursor.execute(f"""
                        CREATE INDEX IF NOT EXISTS idx_label_parent ON {self.noetl_schema}.label(parent_id);
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_label_parent_name ON {self.noetl_schema}.label(parent_id, name);
                        CREATE INDEX IF NOT EXISTS idx_chat_label ON {self.noetl_schema}.chat(label_id);
                        CREATE INDEX IF NOT EXISTS idx_message_chat_created ON {self.noetl_schema}.message(chat_id, created_at);
                        CREATE INDEX IF NOT EXISTS idx_attachment_chat_created ON {self.noetl_schema}.attachment(chat_id, created_at);
                    """)
                except Exception as e:
                    logger.warning(f"Failed to create identity/collab indexes as {self.noetl_user} (sync): {e}. Retrying as admin.")
                    try:
                        admin = psycopg.connect(self.admin_conn)
                        try:
                            admin.autocommit = True
                            with admin.cursor() as ac:
                                ac.execute(f"""
                                    CREATE INDEX IF NOT EXISTS idx_label_parent ON {self.noetl_schema}.label(parent_id);
                                    CREATE UNIQUE INDEX IF NOT EXISTS idx_label_parent_name ON {self.noetl_schema}.label(parent_id, name);
                                    CREATE INDEX IF NOT EXISTS idx_chat_label ON {self.noetl_schema}.chat(label_id);
                                    CREATE INDEX IF NOT EXISTS idx_message_chat_created ON {self.noetl_schema}.message(chat_id, created_at);
                                    CREATE INDEX IF NOT EXISTS idx_attachment_chat_created ON {self.noetl_schema}.attachment(chat_id, created_at);
                                """)
                        finally:
                            admin.close()
                    except Exception as e2:
                        logger.error(f"Admin fallback also failed creating identity/collab indexes (sync): {e2}")
                if not getattr(self.conn, "autocommit", False):
                    self.conn.commit()
                logger.info("Postgres database tables initialized in noetl schema (sync).")
        except Exception as e:
            logger.error(f"FATAL: Error creating postgres tables (sync): {e}", exc_info=True)
            raise

    def test_workload_table_sync(self):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'workload'
                    )
                """, (self.noetl_schema,))
                result = cursor.fetchone()
                table_exists = result[0] if result else False
                if not table_exists:
                    logger.error("FATAL: Failed to create workload table (sync).")
                    raise ValueError("Workload table missing")
                else:
                    logger.info("Workload table present (sync).")
        except Exception as e:
            logger.error(f"FATAL: Error testing workload table (sync): {e}.", exc_info=True)
            raise

    def init_database_sync(self):
        try:
            self.test_connection_sync()
            self.set_search_path_sync()
            self.create_postgres_tables_sync()
            self.test_workload_table_sync()
            return True
        except Exception as e:
            logger.error(f"FATAL: Error initializing database (sync): {e}.", exc_info=True)
            raise

    async def create_noetl_schema(self):
        try:
            logger.info(f"ATTEMPTING TO CREATE SCHEMA: Starting schema installation for '{self.noetl_schema}' with user '{self.noetl_user}'")
            logger.info(f"SCHEMA INSTALLATION: Using admin credentials to connect to database")

            try:
                self.admin_connection = await psycopg.AsyncConnection.connect(self.admin_conn)
                await self.admin_connection.set_autocommit(True)
                logger.info("SCHEMA INSTALLATION: Successfully connected to database with admin credentials (async)")
            except Exception as admin_conn_error:
                logger.error(f"SCHEMA INSTALLATION FAILED: Could not connect with admin credentials: {admin_conn_error}")
                logger.error("SCHEMA INSTALLATION FAILED: Make sure POSTGRES_USER and POSTGRES_PASSWORD environment variables are set correctly")
                raise

            async with self.admin_connection.cursor() as cursor:
                logger.info(f"SCHEMA INSTALLATION: Checking if user '{self.noetl_user}' exists...")
                await cursor.execute("""
                    SELECT 1 FROM pg_roles WHERE rolname = %s
                """, (self.noetl_user,))
                user_exists = await cursor.fetchone()

                if not user_exists:
                    logger.info(f"SCHEMA INSTALLATION: Creating user '{self.noetl_user}'...")
                    await cursor.execute(f"""
                        CREATE USER {self.noetl_user} WITH 
                        PASSWORD '{self.noetl_password}'
                        CREATEDB
                        LOGIN
                    """)
                    logger.info(f"SCHEMA INSTALLATION: User '{self.noetl_user}' created successfully")
                else:
                    logger.info(f"SCHEMA INSTALLATION: User '{self.noetl_user}' already exists")

                logger.info(f"SCHEMA INSTALLATION: Checking if schema '{self.noetl_schema}' exists...")
                await cursor.execute("""
                    SELECT 1 FROM information_schema.schemata WHERE schema_name = %s
                """, (self.noetl_schema,))
                schema_exists = await cursor.fetchone()

                if not schema_exists:
                    logger.info(f"SCHEMA INSTALLATION: Creating schema '{self.noetl_schema}'...")
                    await cursor.execute(f"CREATE SCHEMA {self.noetl_schema}")
                    logger.info(f"SCHEMA INSTALLATION: Schema '{self.noetl_schema}' created successfully")
                else:
                    logger.info(f"SCHEMA INSTALLATION: Schema '{self.noetl_schema}' already exists")

                logger.info(f"SCHEMA INSTALLATION: Granting permissions to user '{self.noetl_user}'...")
                await cursor.execute(f"GRANT ALL PRIVILEGES ON SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                await cursor.execute(f"GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                await cursor.execute(f"GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA {self.noetl_schema} TO {self.noetl_user}")
                await cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {self.noetl_schema} GRANT ALL ON TABLES TO {self.noetl_user}")
                await cursor.execute(f"ALTER DEFAULT PRIVILEGES IN SCHEMA {self.noetl_schema} GRANT ALL ON SEQUENCES TO {self.noetl_user}")

                await self.admin_connection.commit()
                logger.info("SCHEMA INSTALLATION: NoETL user and schema setup completed successfully")

        except Exception as e:
            logger.error(f"SCHEMA INSTALLATION FAILED: Error setting up noetl user and schema: {e}", exc_info=True)
            logger.error(f"SCHEMA INSTALLATION FAILED: Check that POSTGRES_USER has sufficient privileges to create users and schemas")
            logger.error(f"SCHEMA INSTALLATION FAILED: Verify that NOETL_USER, NOETL_PASSWORD, and NOETL_SCHEMA are correctly set")
            if self.admin_connection:
                await self.admin_connection.rollback()
            raise ValueError(f"Schema installation failed: {e}")
        finally:
            if self.admin_connection:
                await self.admin_connection.close()
                self.admin_connection = None

    async def init_database(self):
        try:
            logger.info("Initializing database tables (async).")
            await self.test_connection()
            await self.set_search_path()
            await self.create_postgres_tables()
            tables = await self.list_tables()
            logger.info(f"Tables in noetl schema: {tables}.")

            return True
        except Exception as e:
            logger.error(f"FATAL: Error initializing database: {e}.", exc_info=True)
            logger.error("FATAL: Exiting immediately due to database initialization failure")
            sys.exit(1)

    async def set_search_path(self):
        """Set the search path to use the noetl schema"""
        try:
            async with self.conn.cursor() as cursor:
                await cursor.execute(f"SET search_path TO {self.noetl_schema}, public")
                await self.conn.commit()
                logger.info(f"Search path set to '{self.noetl_schema}, public'")
        except Exception as e:
            logger.error(f"Error setting search path: {e}.", exc_info=True)
            raise

    async def test_connection(self):
        try:
            if self.conn is None:
                logger.error("FATAL: Database connection is None. Connection was not established properly.")
                raise ValueError("Database connection is None")

            async with self.conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                result = await cursor.fetchone()
                if result and result[0] == 1:
                    logger.info("Database connected (async).")
                else:
                    logger.error("FATAL: Database connection test failed.")
                    raise ValueError("Database connection test failed")
        except Exception as e:
            logger.error(f"FATAL: Error testing database connection: {e}.", exc_info=True)
            raise

    async def create_postgres_tables(self):
        try:
            async with self.conn.cursor() as cursor:
                logger.info("Creating resource table (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.resource (
                        name TEXT PRIMARY KEY
                    )
                """)

                logger.info("Creating catalog table (async).")
                await cursor.execute(f"""
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

                logger.info("Creating workload table (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workload (
                        execution_id BIGINT,
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        data TEXT,
                        PRIMARY KEY (execution_id)
                    )
                """)
                await self.test_workload_table()

                logger.info("Creating event table (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.event (
                        execution_id BIGINT,
                        event_id BIGINT,
                        parent_event_id BIGINT,
                        parent_execution_id BIGINT,
                        timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        event_type VARCHAR,
                        node_id VARCHAR,
                        node_name VARCHAR,
                        node_type VARCHAR,
                        status VARCHAR,
                        duration DOUBLE PRECISION,
                        context TEXT,
                        result TEXT,
                        metadata TEXT,
                        error TEXT,
                        loop_id VARCHAR,
                        loop_name VARCHAR,
                        iterator VARCHAR,
                        items TEXT,
                        current_index INTEGER,
                        current_item TEXT,
                        worker_id VARCHAR,
                        distributed_state VARCHAR,
                        context_key VARCHAR,
                        context_value TEXT,
                        trace_component JSONB,
                        stack_trace TEXT,
                        PRIMARY KEY (execution_id, event_id)
                    )
                """)
                # Back-compat: rename event_log -> event if event not present
                try:
                    await cursor.execute(f"SELECT to_regclass('{self.noetl_schema}.event') IS NOT NULL")
                    ev_exists = (await cursor.fetchone() or [False])[0]
                    await cursor.execute(f"SELECT to_regclass('{self.noetl_schema}.event_log') IS NOT NULL")
                    evlog_exists = (await cursor.fetchone() or [False])[0]
                    if (not ev_exists) and evlog_exists:
                        await cursor.execute(f"ALTER TABLE {self.noetl_schema}.event_log RENAME TO event")
                except Exception:
                    pass
                # Ensure helper columns exist
                try:
                    await cursor.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS trace_component JSONB")
                except Exception:
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS trace_component JSONB")
                        await admin_conn.close()
                    except Exception:
                        if not getattr(self.conn, "autocommit", False):
                            await self.conn.rollback()
                try:
                    await cursor.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS parent_execution_id BIGINT")
                except Exception:
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS parent_execution_id BIGINT")
                        await admin_conn.close()
                    except Exception:
                        if not getattr(self.conn, "autocommit", False):
                            await self.conn.rollback()
                try:
                    await cursor.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS stack_trace TEXT")
                except Exception:
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER TABLE {self.noetl_schema}.event ADD COLUMN IF NOT EXISTS stack_trace TEXT")
                        await admin_conn.close()
                    except Exception:
                        if not getattr(self.conn, "autocommit", False):
                            await self.conn.rollback()
                # Back-compat view
                try:
                    await cursor.execute(f"CREATE OR REPLACE VIEW {self.noetl_schema}.event_log AS SELECT * FROM {self.noetl_schema}.event")
                except Exception:
                    pass

                logger.info("Creating workflow table (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workflow (
                        execution_id BIGINT,
                        step_id VARCHAR,
                        step_name VARCHAR,
                        step_type VARCHAR,
                        description TEXT,
                        raw_config TEXT,
                        PRIMARY KEY (execution_id, step_id)
                    )
                """)

                logger.info("Creating workbook table (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.workbook (
                        execution_id BIGINT,
                        task_id VARCHAR,
                        task_name VARCHAR,
                        task_type VARCHAR,
                        raw_config TEXT,
                        PRIMARY KEY (execution_id, task_id)
                    )
                """)

                logger.info("Creating transition table (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.transition (
                        execution_id BIGINT,
                        from_step VARCHAR,
                        to_step VARCHAR,
                        condition TEXT,
                        with_params TEXT,
                        PRIMARY KEY (execution_id, from_step, to_step, condition)
                    )
                """)
            
                # Migrate legacy error_log into event and drop it
                try:
                    await cursor.execute(f"SELECT to_regclass('{self.noetl_schema}.error_log') IS NOT NULL")
                    row = await cursor.fetchone()
                    if row and row[0]:
                        try:
                            await cursor.execute(f"""
                                INSERT INTO {self.noetl_schema}.event (
                                    execution_id, event_id, timestamp, event_type, node_id, node_name, status,
                                    context, result, metadata, error, stack_trace
                                )
                                SELECT 
                                    COALESCE(execution_id, 0) as execution_id,
                                    error_id as event_id,
                                    COALESCE(timestamp, CURRENT_TIMESTAMP) as timestamp,
                                    'error' as event_type,
                                    step_id as node_id,
                                    step_name as node_name,
                                    'FAILED' as status,
                                    context_data::text as context,
                                    output_data::text as result,
                                    json_build_object(
                                        'error_type', error_type,
                                        'severity', severity,
                                        'resolved', resolved,
                                        'resolution_notes', resolution_notes,
                                        'template_string', template_string
                                    )::text as metadata,
                                    error_message as error,
                                    stack_trace as stack_trace
                                FROM {self.noetl_schema}.error_log
                                ON CONFLICT (execution_id, event_id) DO NOTHING
                            """)
                        except Exception:
                            pass
                        try:
                            await cursor.execute(f"DROP TABLE IF EXISTS {self.noetl_schema}.error_log CASCADE")
                        except Exception:
                            pass
                except Exception:
                    pass

                await cursor.execute(f"""
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
                # Ensure credential table is owned by the noetl user so index/alter can proceed
                try:
                    await cursor.execute(f"ALTER TABLE {self.noetl_schema}.credential OWNER TO {self.noetl_user}")
                except Exception:
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER TABLE {self.noetl_schema}.credential OWNER TO {self.noetl_user}")
                        await admin_conn.close()
                    except Exception:
                        pass

                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_credential_type ON {self.noetl_schema}.credential (type);
                """)

                try:
                    await cursor.execute(f"""
                        ALTER TABLE {self.noetl_schema}.catalog ADD COLUMN IF NOT EXISTS credential_id INTEGER;
                    """)
                except Exception:
                    pass

                await self.conn.commit()
                logger.info("Creating runtime table with runtime_id primary key (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.runtime (
                        runtime_id BIGINT PRIMARY KEY,
                        name TEXT NOT NULL,
                        component_type TEXT NOT NULL CHECK (component_type IN ('worker_pool','server_api','broker')),
                        base_url TEXT,
                        status TEXT NOT NULL,
                        labels JSONB,
                        capabilities JSONB,
                        capacity INTEGER,
                        runtime JSONB,
                        last_heartbeat TIMESTAMPTZ NOT NULL DEFAULT now(),
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
                    )
                """)
                try:
                    await cursor.execute(f"ALTER TABLE {self.noetl_schema}.runtime OWNER TO {self.noetl_user}")
                except Exception:
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER TABLE {self.noetl_schema}.runtime OWNER TO {self.noetl_user}")
                        await admin_conn.close()
                    except Exception:
                        pass
                await cursor.execute(f"""
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_component_name ON {self.noetl_schema}.runtime (component_type, name);
                """)
                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_runtime_type ON {self.noetl_schema}.runtime (component_type);
                """)
                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_runtime_status ON {self.noetl_schema}.runtime (status);
                """)
                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_runtime_runtime_type ON {self.noetl_schema}.runtime ((runtime->>'type'));
                """)

                # ===== Schedule table (async) =====
                logger.info("Creating schedule table (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.schedule (
                        schedule_id BIGSERIAL PRIMARY KEY,
                        playbook_path TEXT NOT NULL,
                        playbook_version TEXT,
                        cron TEXT,
                        interval_seconds INTEGER,
                        enabled BOOLEAN NOT NULL DEFAULT TRUE,
                        timezone TEXT DEFAULT 'UTC',
                        next_run_at TIMESTAMPTZ,
                        last_run_at TIMESTAMPTZ,
                        last_status TEXT,
                        input_payload JSONB,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        meta JSONB
                    )
                """)
                # Ensure ownership for schedule table before indexes
                try:
                    await cursor.execute(f"ALTER TABLE {self.noetl_schema}.schedule OWNER TO {self.noetl_user}")
                except Exception:
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER TABLE {self.noetl_schema}.schedule OWNER TO {self.noetl_user}")
                        await admin_conn.close()
                    except Exception:
                        pass
                await cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_schedule_next_run ON {self.noetl_schema}.schedule (next_run_at) WHERE enabled = TRUE;")
                await cursor.execute(f"CREATE INDEX IF NOT EXISTS idx_schedule_playbook ON {self.noetl_schema}.schedule (playbook_path);")

                # ===== Queue table (work dispatch) =====
                logger.info("Creating queue table (async).")
                queue_sql = f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.queue (
                        id BIGSERIAL PRIMARY KEY,
                        created_at TIMESTAMPTZ DEFAULT now(),
                        available_at TIMESTAMPTZ DEFAULT now(),
                        lease_until TIMESTAMPTZ,
                        last_heartbeat TIMESTAMPTZ,
                        status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','leased','done','failed','dead')),
                        execution_id BIGINT NOT NULL,
                        node_id TEXT NOT NULL,
                        action TEXT NOT NULL,
                        context JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        priority INT NOT NULL DEFAULT 0,
                        attempts INT NOT NULL DEFAULT 0,
                        max_attempts INT NOT NULL DEFAULT 5,
                        worker_id TEXT
                    )
                """
                await cursor.execute(queue_sql)
                try:
                    await cursor.execute(f"ALTER TABLE {self.noetl_schema}.queue OWNER TO {self.noetl_user}")
                except Exception:
                    # Try admin fallback when table is owned by a different role
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER TABLE {self.noetl_schema}.queue OWNER TO {self.noetl_user}")
                        await admin_conn.close()
                    except Exception:
                        pass
                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_status_available ON {self.noetl_schema}.queue (status, available_at, priority DESC, id)
                """)
                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_exec ON {self.noetl_schema}.queue (execution_id)
                """)
                try:
                    await cursor.execute(f"""
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_exec_node ON {self.noetl_schema}.queue (execution_id, node_id)
                    """)
                except Exception as e:
                    logger.warning(f"Skipping unique index creation idx_queue_exec_node (async) (possible duplicates present): {e}")
                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_worker ON {self.noetl_schema}.queue (worker_id)
                """)
                await cursor.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_queue_lease_until ON {self.noetl_schema}.queue (lease_until)
                """)

                # ===== Identity & Collaboration tables (async) =====
                logger.info("Creating identity & collaboration tables (async).")
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.role (
                        id BIGINT PRIMARY KEY,
                        name TEXT UNIQUE NOT NULL,
                        description TEXT
                    )
                """)
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.profile (
                        id BIGINT PRIMARY KEY,
                        username TEXT UNIQUE NOT NULL,
                        email TEXT UNIQUE,
                        password_hash TEXT,
                        role_id BIGINT REFERENCES {self.noetl_schema}.role(id),
                        type TEXT NOT NULL CHECK (type IN ('user','bot')),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.session (
                        id BIGINT PRIMARY KEY,
                        profile_id BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        session_type TEXT NOT NULL CHECK (session_type IN ('user','bot','ai')),
                        connected_at TIMESTAMPTZ DEFAULT now(),
                        disconnected_at TIMESTAMPTZ,
                        metadata JSONB
                    )
                """)
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.label (
                        id BIGINT PRIMARY KEY,
                        parent_id BIGINT REFERENCES {self.noetl_schema}.label(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        owner_id BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.chat (
                        id BIGINT PRIMARY KEY,
                        label_id BIGINT REFERENCES {self.noetl_schema}.label(id) ON DELETE CASCADE,
                        name TEXT NOT NULL,
                        owner_id BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.member (
                        id BIGINT PRIMARY KEY,
                        chat_id BIGINT REFERENCES {self.noetl_schema}.chat(id) ON DELETE CASCADE,
                        profile_id BIGINT REFERENCES {self.noetl_schema}.profile(id) ON DELETE CASCADE,
                        role TEXT NOT NULL CHECK (role IN ('owner','admin','member')),
                        joined_at TIMESTAMPTZ DEFAULT now(),
                        UNIQUE(chat_id, profile_id)
                    )
                """)
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.message (
                        id BIGINT PRIMARY KEY,
                        chat_id BIGINT REFERENCES {self.noetl_schema}.chat(id) ON DELETE CASCADE,
                        sender_type TEXT NOT NULL CHECK (sender_type IN ('user','bot','ai','system')),
                        sender_id BIGINT,
                        role TEXT,
                        content TEXT NOT NULL,
                        metadata JSONB,
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                await cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS {self.noetl_schema}.attachment (
                        id BIGINT PRIMARY KEY,
                        label_id BIGINT REFERENCES {self.noetl_schema}.label(id) ON DELETE CASCADE,
                        chat_id BIGINT REFERENCES {self.noetl_schema}.chat(id) ON DELETE CASCADE,
                        filename TEXT NOT NULL,
                        filepath TEXT NOT NULL,
                        uploaded_by BIGINT REFERENCES {self.noetl_schema}.profile(id),
                        created_at TIMESTAMPTZ DEFAULT now()
                    )
                """)
                try:
                    await cursor.execute(f"""
                        CREATE INDEX IF NOT EXISTS idx_label_parent ON {self.noetl_schema}.label(parent_id);
                        CREATE UNIQUE INDEX IF NOT EXISTS idx_label_parent_name ON {self.noetl_schema}.label(parent_id, name);
                        CREATE INDEX IF NOT EXISTS idx_chat_label ON {self.noetl_schema}.chat(label_id);
                        CREATE INDEX IF NOT EXISTS idx_message_chat_created ON {self.noetl_schema}.message(chat_id, created_at);
                        CREATE INDEX IF NOT EXISTS idx_attachment_chat_created ON {self.noetl_schema}.attachment(chat_id, created_at);
                    """)
                except Exception as e:
                    logger.warning(f"Failed to create identity/collab indexes as {self.noetl_user} (async): {e}. Retrying as admin.")
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        try:
                            await admin_conn.set_autocommit(True)
                            async with admin_conn.cursor() as ac:
                                await ac.execute(f"""
                                    CREATE INDEX IF NOT EXISTS idx_label_parent ON {self.noetl_schema}.label(parent_id);
                                    CREATE UNIQUE INDEX IF NOT EXISTS idx_label_parent_name ON {self.noetl_schema}.label(parent_id, name);
                                    CREATE INDEX IF NOT EXISTS idx_chat_label ON {self.noetl_schema}.chat(label_id);
                                    CREATE INDEX IF NOT EXISTS idx_message_chat_created ON {self.noetl_schema}.message(chat_id, created_at);
                                    CREATE INDEX IF NOT EXISTS idx_attachment_chat_created ON {self.noetl_schema}.attachment(chat_id, created_at);
                                """)
                        finally:
                            await admin_conn.close()
                    except Exception as e2:
                        logger.error(f"Admin fallback also failed creating identity/collab indexes (async): {e2}")

                # Snowflake-like ID function (best-effort) and defaults
                try:
                    await cursor.execute(f"""
                        CREATE OR REPLACE FUNCTION {self.noetl_schema}.snowflake_id() RETURNS BIGINT AS $$
                        DECLARE
                            our_epoch BIGINT := 1704067200000; -- 2024-01-01 UTC in ms
                            seq_id BIGINT;
                            now_ms BIGINT;
                            shard_id INT := 1; -- single shard default
                        BEGIN
                            SELECT nextval('{self.noetl_schema}.snowflake_seq') % 1024 INTO seq_id;
                            now_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
                            RETURN ((now_ms - our_epoch) << 23) |
                                   ((shard_id & 31) << 18) |
                                   (seq_id & 262143);
                        END;
                        $$ LANGUAGE plpgsql;
                    """)
                except Exception as e:
                    # If function exists with different owner, try to change owner via admin and retry
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER FUNCTION {self.noetl_schema}.snowflake_id() OWNER TO {self.noetl_user}")
                        await admin_conn.close()
                    except Exception:
                        pass
                    try:
                        await cursor.execute(f"""
                            CREATE OR REPLACE FUNCTION {self.noetl_schema}.snowflake_id() RETURNS BIGINT AS $$
                            DECLARE
                                our_epoch BIGINT := 1704067200000; -- 2024-01-01 UTC in ms
                                seq_id BIGINT;
                                now_ms BIGINT;
                                shard_id INT := 1; -- single shard default
                            BEGIN
                                SELECT nextval('{self.noetl_schema}.snowflake_seq') % 1024 INTO seq_id;
                                now_ms := (EXTRACT(EPOCH FROM clock_timestamp()) * 1000)::BIGINT;
                                RETURN ((now_ms - our_epoch) << 23) |
                                       ((shard_id & 31) << 18) |
                                       (seq_id & 262143);
                            END;
                            $$ LANGUAGE plpgsql;
                        """)
                    except Exception:
                        pass

                # Sequence and ownership
                await cursor.execute(f"CREATE SEQUENCE IF NOT EXISTS {self.noetl_schema}.snowflake_seq;")
                try:
                    await cursor.execute(f"ALTER SEQUENCE {self.noetl_schema}.snowflake_seq OWNER TO {self.noetl_user}")
                except Exception:
                    try:
                        admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                        await admin_conn.set_autocommit(True)
                        async with admin_conn.cursor() as ac:
                            await ac.execute(f"ALTER SEQUENCE {self.noetl_schema}.snowflake_seq OWNER TO {self.noetl_user}")
                        await admin_conn.close()
                    except Exception:
                        pass
                for tbl in ['role','profile','session','label','chat','member','message','attachment']:
                    try:
                        await cursor.execute(f"ALTER TABLE {self.noetl_schema}." + tbl + " ALTER COLUMN id SET DEFAULT {self.noetl_schema}.snowflake_id();")
                    except Exception:
                        pass

                try:
                    try:
                        from noetl.core.common import get_snowflake_id
                    except Exception:
                        get_snowflake_id = lambda: int(datetime.datetime.now().timestamp() * 1000)

                    await cursor.execute(f"SELECT component_type, name FROM {self.noetl_schema}.runtime WHERE runtime_id IS NULL")
                    rows_to_update = await cursor.fetchall()
                    for row in rows_to_update:
                        comp, name = row[0], row[1]
                        sf = get_snowflake_id()
                        await cursor.execute(f"UPDATE {self.noetl_schema}.runtime SET runtime_id = %s WHERE component_type = %s AND name = %s AND runtime_id IS NULL", (sf, comp, name))

                    await cursor.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_runtime_id ON {self.noetl_schema}.runtime (runtime_id);")

                    await cursor.execute("""
                        SELECT tc.constraint_name, kc.column_name
                        FROM information_schema.table_constraints tc
                        JOIN information_schema.key_column_usage kc ON kc.constraint_name = tc.constraint_name
                        WHERE tc.table_schema = %s AND tc.table_name = 'runtime' AND tc.constraint_type = 'PRIMARY KEY'
                    """, (self.noetl_schema,))
                    pk_info = await cursor.fetchall()
                    pk_columns = [r[1] for r in pk_info] if pk_info else []
                    if pk_columns and not (len(pk_columns) == 1 and pk_columns[0] == 'runtime_id'):
                        constraint_name = pk_info[0][0]
                        try:
                            await cursor.execute(f"ALTER TABLE {self.noetl_schema}.runtime DROP CONSTRAINT {constraint_name}")
                            await cursor.execute(f"ALTER TABLE {self.noetl_schema}.runtime ADD PRIMARY KEY (runtime_id)")
                        except Exception as e:
                            logger.info(f"Could not replace primary key on runtime as noetl user, retrying as admin: {e}")
                            try:
                                admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
                                await admin_conn.set_autocommit(True)
                                async with admin_conn.cursor() as ac:
                                    await ac.execute(f"ALTER TABLE {self.noetl_schema}.runtime DROP CONSTRAINT {constraint_name}")
                                    await ac.execute(f"ALTER TABLE {self.noetl_schema}.runtime ADD PRIMARY KEY (runtime_id)")
                                await admin_conn.close()
                            except Exception:
                                logger.info("Could not replace primary key on runtime automatically; leaving existing PK in place.")

                    await self.conn.commit()
                except Exception:
                    logger.exception("Runtime registry migration to runtime_id primary key encountered an issue; manual migration may be required.")
                logger.info("Postgres database tables initialized in noetl schema (async).")

        except Exception as e:
            logger.error(f"FATAL: Error creating postgres tables: {e}", exc_info=True)
            raise

    async def test_workload_table(self):
        try:
            async with self.conn.cursor() as cursor:
                await cursor.execute(f"""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'workload'
                    )
                """, (self.noetl_schema,))
                result = await cursor.fetchone()
                table_exists = result[0] if result else False

                if not table_exists:
                    logger.error("FATAL: Failed to create workload table.")
                    raise ValueError("Failed to create workload table")
                else:
                    logger.info("Workload table created (async).")

                    try:
                        test_id = get_snowflake_id()
                        test_data = json.dumps({"test": "data"})
                        logger.info(f"Testing workload table with test_id: {test_id}.")

                        await cursor.execute(f"""
                            INSERT INTO {self.noetl_schema}.workload (execution_id, data)
                            VALUES (%s, %s)
                            ON CONFLICT (execution_id) DO UPDATE
                            SET data = EXCLUDED.data
                        """, (test_id, test_data))
                        await self.conn.commit()

                        await cursor.execute(f"""
                            SELECT data FROM {self.noetl_schema}.workload WHERE execution_id = %s
                        """, (test_id,))
                        row = await cursor.fetchone()
                        if row and row[0] == test_data:
                            logger.info("Tested workload table insert and select (async).")
                        else:
                            logger.error(f"FATAL: Failed to verify test data in workload table. Expected: {test_data}, Got: {row[0] if row else None}")
                            raise ValueError("Workload table test failed")

                        await cursor.execute(f"""
                            DELETE FROM {self.noetl_schema}.workload WHERE execution_id = %s
                        """, (test_id,))
                        await self.conn.commit()
                        logger.info("Cleaned up test data from workload table (async).")

                    except Exception as e:
                        logger.error(f"FATAL: Error testing workload table: {e}.", exc_info=True)
                        raise
        except Exception as e:
            logger.error(f"FATAL: Error testing workload table: {e}.", exc_info=True)
            raise

    async def list_tables(self) -> List[str]:
        try:
            async with self.conn.cursor() as cursor:
                await cursor.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = %s
                """, (self.noetl_schema,))
                rows = await cursor.fetchall()
                return [row[0] for row in rows]
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
            target = (self.noetl_schema or "").strip()
            if not target:
                raise ValueError("NOETL_SCHEMA is empty or not set; refusing to drop schema")
            reserved = {"public", "pg_catalog", "information_schema"}
            if target.lower() in reserved:
                raise ValueError(f"Refusing to drop reserved schema '{target}'")
            logger.warning(f"[ADMIN] Dropping schema '{target}' and all its objects.")
            self.admin_connection = psycopg.connect(self.admin_conn)

            with self.admin_connection.cursor() as cursor:
                cursor.execute(f"DROP SCHEMA IF EXISTS {target} CASCADE")
                self.admin_connection.commit()
                logger.info(f"[ADMIN] Schema '{target}' dropped.")

        except Exception as e:
            logger.error(f"Error dropping schema: {e}.", exc_info=True)
            if self.admin_connection:
                self.admin_connection.rollback()
            raise
        finally:
            if self.admin_connection:
                self.admin_connection.close()
                self.admin_connection = None

    async def drop_noetl_schema_async(self):
        """Async drop of the entire noetl schema and all its objects using admin credentials"""
        try:
            target = (self.noetl_schema or "").strip()
            if not target:
                raise ValueError("NOETL_SCHEMA is empty or not set; refusing to drop schema")
            reserved = {"public", "pg_catalog", "information_schema"}
            if target.lower() in reserved:
                raise ValueError(f"Refusing to drop reserved schema '{target}'")

            logger.warning(f"[ADMIN] Dropping schema '{target}' and all its objects (async).")
            admin_conn = await psycopg.AsyncConnection.connect(self.admin_conn)
            try:
                await admin_conn.set_autocommit(True)
                async with admin_conn.cursor() as cursor:
                    await cursor.execute(f"DROP SCHEMA IF EXISTS {target} CASCADE")
                logger.info(f"[ADMIN] Schema '{target}' dropped (async).")
            finally:
                await admin_conn.close()
        except Exception as e:
            logger.error(f"Error dropping schema (async): {e}.", exc_info=True)
            raise

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
        Log an error as an event into the unified event table.
        
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
                self.initialize_connection_sync()
                
            with self.conn.cursor() as cursor:
                try:
                    from noetl.core.common import get_snowflake_id
                except Exception:
                    get_snowflake_id = lambda: int(datetime.datetime.now().timestamp() * 1000)
                event_id = get_snowflake_id()
                # Build metadata envelope (as text) for extra details
                meta_env = json.dumps(make_serializable({
                    'error_type': error_type,
                    'severity': severity,
                    'template_string': template_string,
                    'input_data': make_serializable(input_data),
                    'output_data': make_serializable(output_data)
                }))
                cursor.execute(f"""
                    INSERT INTO {self.noetl_schema}.event (
                        execution_id, event_id, timestamp, event_type, node_id, node_name, status,
                        context, result, metadata, error, stack_trace
                    ) VALUES (
                        %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    ) RETURNING event_id
                """, (
                    execution_id, event_id, 'error', step_id, step_name, 'FAILED',
                    context_data_json, output_data_json, meta_env, error_message, stack_trace
                ))
                inserted = cursor.fetchone()[0]
                self.conn.commit()
                logger.info(f"Logged error event with event_id: {inserted}")
                return inserted
                
        except Exception as e:
            logger.error(f"Failed to log error to error_log table: {e}", exc_info=True)
            if self.conn:
                try:
                    self.conn.rollback()
                except:
                    pass
            return None
    
    def mark_error_resolved(self, error_event_id: int, resolution_notes: str = None) -> bool:
        """Record an 'error_resolved' event in the unified event table."""
        try:
            if not self.conn or self.conn.closed:
                self.initialize_connection_sync()
            with self.conn.cursor() as cursor:
                cursor.execute(f"""
                    INSERT INTO {self.noetl_schema}.event (execution_id, event_id, timestamp, event_type, status, metadata)
                    VALUES (%s, %s, CURRENT_TIMESTAMP, 'error_resolved', 'COMPLETED', %s)
                """, (
                    0, error_event_id, json.dumps({'resolution_notes': resolution_notes}) if resolution_notes else None
                ))
                self.conn.commit()
                return True
        except Exception:
            try:
                self.conn.rollback()
            except Exception:
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
                self.initialize_connection_sync()
                
            query = f"SELECT execution_id, event_id, timestamp, node_id, node_name, error, metadata, stack_trace FROM {self.noetl_schema}.event WHERE event_type = 'error'"
            params = []
            if error_type:
                query += " AND metadata LIKE %s"
                params.append(f'%"error_type": "{error_type}"%')
            if execution_id:
                query += " AND execution_id = %s"
                params.append(execution_id)
            # 'resolved' state is not a first-class column; skip
            query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            with self.conn.cursor() as cursor:
                cursor.execute(query, params)
                rows = cursor.fetchall()
                errors: List[Dict[str, Any]] = []
                for exec_id, eid, ts, node_id, node_name, err, meta_txt, stack in rows:
                    try:
                        meta = json.loads(meta_txt) if isinstance(meta_txt, str) else (meta_txt or {})
                    except Exception:
                        meta = meta_txt or {}
                    errors.append({
                        'execution_id': exec_id,
                        'event_id': eid,
                        'timestamp': ts.isoformat() if hasattr(ts, 'isoformat') else ts,
                        'step_id': node_id,
                        'step_name': node_name,
                        'error_message': err,
                        'metadata': meta,
                        'stack_trace': stack,
                    })
                return errors
                
        except Exception as e:
            logger.error(f"Failed to get errors from error_log table: {e}", exc_info=True)
            return []
    
    async def log_error_async(self, 
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
        try:
            if stack_trace is None and error_type == "template_rendering":
                stack_trace = ''.join(traceback.format_stack())

            context_data_json = json.dumps(make_serializable(context_data)) if context_data else None
            input_data_json = json.dumps(make_serializable(input_data)) if input_data else None
            output_data_json = json.dumps(make_serializable(output_data)) if output_data else None

            if not self.conn or getattr(self.conn, 'closed', False):
                await self.initialize_connection()

            async with self.conn.cursor() as cursor:
                try:
                    from noetl.core.common import get_snowflake_id
                except Exception:
                    get_snowflake_id = lambda: int(datetime.datetime.now().timestamp() * 1000)
                event_id = get_snowflake_id()
                meta_env = json.dumps(make_serializable({
                    'error_type': error_type,
                    'severity': severity,
                    'template_string': template_string,
                    'input_data': make_serializable(input_data),
                    'output_data': make_serializable(output_data)
                }))
                await cursor.execute(f"""
                    INSERT INTO {self.noetl_schema}.event (
                        execution_id, event_id, timestamp, event_type, node_id, node_name, status,
                        context, result, metadata, error, stack_trace
                    ) VALUES (
                        %s, %s, CURRENT_TIMESTAMP, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s
                    ) RETURNING event_id
                """, (
                    execution_id, event_id, 'error', step_id, step_name, 'FAILED',
                    context_data_json, output_data_json, meta_env, error_message, stack_trace
                ))
                row = await cursor.fetchone()
                await self.conn.commit()
                event_row_id = row[0] if row else None
                logger.info(f"Logged error event with event_id: {event_row_id}")
                return event_row_id
        except Exception as e:
            logger.error(f"Failed to log error (async): {e}", exc_info=True)
            try:
                if self.conn and not getattr(self.conn, 'autocommit', False):
                    await self.conn.rollback()
            except Exception:
                pass
            return None

    async def mark_error_resolved_async(self, error_event_id: int, resolution_notes: str = None) -> bool:
        try:
            if not self.conn or getattr(self.conn, 'closed', False):
                await self.initialize_connection()
            async with self.conn.cursor() as cursor:
                await cursor.execute(f"""
                    INSERT INTO {self.noetl_schema}.event (execution_id, event_id, timestamp, event_type, status, metadata)
                    VALUES (%s, %s, CURRENT_TIMESTAMP, 'error_resolved', 'COMPLETED', %s)
                """, (
                    0, error_event_id, json.dumps({'resolution_notes': resolution_notes}) if resolution_notes else None
                ))
                await self.conn.commit()
                return True
        except Exception:
            try:
                if self.conn and not getattr(self.conn, 'autocommit', False):
                    await self.conn.rollback()
            except Exception:
                pass
            return False

    async def get_errors_async(self,
                  error_type: str = None,
                  execution_id: str = None,
                  resolved: bool = None,
                  limit: int = 100,
                  offset: int = 0) -> List[Dict]:
        try:
            if not self.conn or getattr(self.conn, 'closed', False):
                await self.initialize_connection()

            query = f"SELECT * FROM {self.noetl_schema}.event WHERE event_type = 'error'"
            params: list[Any] = []
            if error_type:
                query += " AND metadata LIKE %s"
                params.append(f'%"error_type": "{error_type}"%')
            if execution_id:
                query += " AND execution_id = %s"
                params.append(execution_id)
            # resolved filter not supported in unified event table; encode in metadata if needed
            query += " ORDER BY timestamp DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            async with self.conn.cursor() as cursor:
                await cursor.execute(query, params)
                rows = await cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]
                errors: List[Dict[str, Any]] = []
                for row in rows:
                    error_dict = dict(zip(columns, row))
                    for field in ['context_data', 'input_data', 'output_data']:
                        if error_dict.get(field) and isinstance(error_dict[field], str):
                            try:
                                error_dict[field] = json.loads(error_dict[field])
                            except Exception:
                                pass
                    errors.append(error_dict)
                return errors
        except Exception as e:
            logger.error(f"Failed to get errors from error_log table (async): {e}", exc_info=True)
            return []

    async def close(self):
        if self.conn:
            try:
                await self.conn.close()
                logger.info("Database connection closed (async).")
            except Exception as e:
                logger.error(f"Error closing database connection: {e}.", exc_info=True)
