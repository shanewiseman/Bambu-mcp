from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from bambu_mcp.config import Settings
from bambu_mcp.database import harden_sqlite_file
from bambu_mcp.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
target_metadata = Base.metadata


def configured_database_url() -> str:
    """Load settings for standalone Alembic CLI execution."""
    database_url = Settings().database_url
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return database_url


def run_migrations_offline() -> None:
    database_url = configured_database_url()
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        run_migrations(supplied_connection)
        return

    database_url = configured_database_url()
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    try:
        with connectable.connect() as connection:
            run_migrations(connection)
    finally:
        connectable.dispose()
    harden_sqlite_file(database_url)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
