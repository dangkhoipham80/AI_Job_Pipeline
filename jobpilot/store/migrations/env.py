"""Alembic environment — targets Postgres, driven by Secrets.database_url.

Ensures the ``jobpilot`` schema exists and keeps the Alembic version table in
that schema, so migrations and app models share one namespace.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from jobpilot.config import get_secrets
from jobpilot.store.db import SCHEMA, Base, make_engine

# Import models so their tables register on Base.metadata for autogenerate.
import jobpilot.store.models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    return get_secrets().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = make_engine(_url())
    with connectable.connect() as connection:
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
        connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
