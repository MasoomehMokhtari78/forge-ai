"""
Integration tests for the Repository model and database foundation.

These tests require a running PostgreSQL instance (docker compose up -d postgres)
and the forgeai_test database to exist:
    docker compose exec postgres createdb -U forgeai forgeai_test

All tests use the db_session fixture defined in conftest.py, which wraps each
test in a transaction that is rolled back afterwards, ensuring full isolation.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.models.repository import IngestionStatus, Repository


async def test_database_connection(db_session):
    """Verify that a database connection can be established and a simple query runs."""
    result = await db_session.execute(text("SELECT 1"))
    assert result.scalar() == 1


async def test_create_repository(db_session):
    """Verify that a Repository row can be inserted and its fields are populated."""
    repo = Repository(
        url="https://github.com/test/create-repo",
        name="test/create-repo",
    )
    db_session.add(repo)
    await db_session.flush()  # flush to DB within the transaction; does not commit

    assert repo.id is not None, "UUID should be generated on instantiation"
    assert repo.status == IngestionStatus.PENDING, "Status should default to PENDING"
    assert repo.created_at is not None, "created_at should be set by the DB on insert"
    assert repo.error_message is None
    assert repo.ingested_at is None


async def test_get_repository_by_id(db_session):
    """Verify that a Repository can be retrieved by its primary key."""
    repo = Repository(
        url="https://github.com/test/get-by-id",
        name="test/get-by-id",
    )
    db_session.add(repo)
    await db_session.flush()

    fetched = await db_session.get(Repository, repo.id)

    assert fetched is not None
    assert fetched.url == "https://github.com/test/get-by-id"
    assert fetched.name == "test/get-by-id"
    assert fetched.status == IngestionStatus.PENDING


async def test_get_repository_by_url(db_session):
    """Verify that a Repository can be queried by URL."""
    repo = Repository(
        url="https://github.com/test/get-by-url",
        name="test/get-by-url",
    )
    db_session.add(repo)
    await db_session.flush()

    result = await db_session.execute(
        select(Repository).where(
            Repository.url == "https://github.com/test/get-by-url"
        )
    )
    fetched = result.scalar_one_or_none()

    assert fetched is not None
    assert fetched.id == repo.id


async def test_url_uniqueness_enforced(db_session):
    """Verify that inserting two Repositories with the same URL raises IntegrityError."""
    url = "https://github.com/test/duplicate-url"
    repo1 = Repository(url=url, name="test/duplicate-url")
    db_session.add(repo1)
    await db_session.flush()

    repo2 = Repository(url=url, name="test/duplicate-url")
    db_session.add(repo2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_default_ingestion_status(db_session):
    """Verify that ingestion_status defaults to PENDING when not explicitly set."""
    repo = Repository(
        url="https://github.com/test/default-status",
        name="test/default-status",
    )
    db_session.add(repo)
    await db_session.flush()

    assert repo.status == IngestionStatus.PENDING


async def test_nullable_fields_are_null_by_default(db_session):
    """Verify that optional fields (error_message, ingested_at) are null by default."""
    repo = Repository(
        url="https://github.com/test/nullables",
        name="test/nullables",
    )
    db_session.add(repo)
    await db_session.flush()

    assert repo.error_message is None
    assert repo.ingested_at is None


async def test_status_can_be_updated(db_session):
    """Verify that ingestion_status can be transitioned through valid states."""
    repo = Repository(
        url="https://github.com/test/status-update",
        name="test/status-update",
    )
    db_session.add(repo)
    await db_session.flush()
    assert repo.status == IngestionStatus.PENDING

    repo.status = IngestionStatus.PROCESSING
    await db_session.flush()
    assert repo.status == IngestionStatus.PROCESSING

    repo.status = IngestionStatus.FAILED
    repo.error_message = "Network timeout during clone"
    await db_session.flush()
    assert repo.status == IngestionStatus.FAILED
    assert repo.error_message == "Network timeout during clone"
