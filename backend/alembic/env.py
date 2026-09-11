"""
Alembic migration environment — async-aware configuration.

Key responsibilities:
  1. Read the database URL from our application Settings (not from alembic.ini),
     keeping configuration in one place.
  2. Import all ORM models so that Alembic's autogenerate can detect the full
     schema. Models are imported via `app.models` which re-exports them all.
  3. Run migrations using an async engine, consistent with how the FastAPI
     application itself connects to the database.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.models.base import Base
import app.models  # noqa: F401 — registers all models with Base.metadata

# Alembic Config object providing access to alembic.ini values.
config = context.config

# Override sqlalchemy.url with the value from our Settings object.
# This ensures Alembic always uses the same connection string as the application.
config.set_main_option("sqlalchemy.url", settings.database_url)

# Configure Python logging from alembic.ini if the config file is present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata that Alembic inspects to detect schema changes.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generates SQL without connecting).

    Useful for generating migration scripts to review or apply manually.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Execute migrations against an open connection (sync wrapper for async)."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode using an async engine.

    NullPool is used here because Alembic is a short-lived CLI process —
    connection pooling provides no benefit and only adds overhead.
    """
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    import sys
    if sys.platform == "win32":
        import selectors
        class _SelectorPolicy(asyncio.DefaultEventLoopPolicy):
            def new_event_loop(self):
                return asyncio.SelectorEventLoop(selectors.SelectSelector())
        asyncio.set_event_loop_policy(_SelectorPolicy())
    asyncio.run(run_migrations_online())

