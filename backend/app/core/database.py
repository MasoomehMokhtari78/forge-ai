"""
SQLAlchemy async engine and session infrastructure.

This module owns the database connection lifecycle:
  - One engine is created at application startup (connection pool).
  - One session is opened per HTTP request via the get_db() dependency,
    committed on success, or rolled back on any exception.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

# The engine manages the underlying connection pool.
# echo=False keeps SQL out of logs by default; flip to True locally when debugging.
engine = create_async_engine(
    settings.database_url,
    echo=False,
)

# async_sessionmaker is the factory for AsyncSession objects.
# expire_on_commit=False: after a commit, ORM attributes remain accessible
# without triggering a lazy-load (which is not supported in async mode).
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides a database session for the duration of a request.

    Usage in a route:
        async def my_route(db: AsyncSession = Depends(get_db)): ...

    The session is committed on success or rolled back on any unhandled exception.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
