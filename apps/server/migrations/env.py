"""Alembic environment. Reads the database URL from YYAI_DATABASE_URL or the client config."""

import os

from alembic import context
from sqlalchemy import create_engine, pool


def _database_url() -> str:
    url = os.environ.get("YYAI_DATABASE_URL")
    if url:
        return url
    from yyai.core.config import load_config

    return load_config().database_url


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=None)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    context.configure(url=_database_url(), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
