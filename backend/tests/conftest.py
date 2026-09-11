import os
import sys

# psycopg v3 requires SelectorEventLoop on Windows; Python defaults to ProactorEventLoop.
# WindowsSelectorEventLoopPolicy is deprecated in 3.14+, so we use loop_factory directly
# via a custom policy that works on all Python versions.
if sys.platform == "win32":
    import asyncio
    import selectors

    class _SelectorPolicy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self):
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

    asyncio.set_event_loop_policy(_SelectorPolicy())

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.main import app as fastapi_app
from app.models.base import Base
import app.models  # noqa: F401 — registers all models with Base.metadata


from sqlalchemy import text
from app.core.database import get_db

# ---------------------------------------------------------------------------
# HTTP client (bound to test database via dependency override)
# ---------------------------------------------------------------------------

@pytest.fixture
def client(test_engine):
    async def override_get_db():
        async with AsyncSession(test_engine, expire_on_commit=False) as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    fastapi_app.dependency_overrides[get_db] = override_get_db
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture(autouse=True)
async def clean_database(test_engine):
    """Ensure all tables are truncated between tests for clean state."""
    yield
    async with test_engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE repositories CASCADE"))



# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://forgeai:forgeai@localhost:5432/forgeai_test",
)


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create an async engine and build the full schema once per test session.

    Using a dedicated test database (forgeai_test) keeps test data entirely
    separate from the development database.

    Create the test database once before running tests:
        docker compose exec postgres createdb -U forgeai forgeai_test
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # Drop any leftover schema from a previous failed run, then rebuild clean.
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Teardown: drop all tables so the test DB is pristine for the next run.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(test_engine):
    """Provide a database session for a single test, isolated via transaction rollback.

    Each test gets a fresh connection with an open transaction. The transaction
    is always rolled back after the test, so inserts/updates/deletes made during
    the test never persist between tests. This avoids the overhead of dropping
    and recreating tables for every test function.
    """
    async with test_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False)
        try:
            yield session
        finally:
            await session.close()
            await conn.rollback()

