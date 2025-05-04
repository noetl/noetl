from logging.config import fileConfig
import os
from sqlalchemy import engine_from_config, pool
from alembic import context
from sqlmodel import SQLModel
from alembic.autogenerate import renderers
from sqlmodel.sql.sqltypes import AutoString
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy import Text
from noetl.api.models import *
from noetl.config.settings import AppConfig
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)
config = context.config
logger.info(f"Alembic env.py from: {os.path.abspath(__file__)}")
script_location = AppConfig().alembic.script_location
logger.info(f"Resolved script_location: {script_location}")

config.set_main_option("script_location", script_location)

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = SQLModel.metadata

@renderers.dispatch_for(AutoString)
def render_auto_string(type_, autogen_context):
    return "sqlmodel.sql.sqltypes.AutoString()"

@renderers.dispatch_for(JSON)
def render_json(type_, autogen_context):
   return "postgresql.JSON(astext_type=Text())"


def get_database_url():
    url = AppConfig().postgres.sqlalchemy_uri()
    logger.info(f"Database URL: {url}")
    return url



def configure_context(connection=None) -> None:
    context.configure(
        connection=connection,
        url=get_database_url() if connection is None else None,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
    )


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()




def run_migrations_online() -> None:
    engine = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with engine.connect() as connection:
        print("Online mode configuration:")
        print("Target Metadata: ", target_metadata.tables.keys())
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
