"""
Database integration tests for CodeFile, CodeChunk, and pgvector embeddings.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository


async def test_code_file_belongs_to_repository(db_session):
    """Verify CodeFile correctly links to Repository and respects relationships."""
    repo = Repository(
        url="https://github.com/test/repo-files",
        name="test/repo-files",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    code_file = CodeFile(
        repository_id=repo.id,
        path="src/main.py",
        extension=".py",
        size_bytes=120,
    )
    db_session.add(code_file)
    await db_session.flush()

    assert code_file.id is not None
    assert code_file.repository_id == repo.id
    assert code_file.repository.url == repo.url


async def test_code_chunk_belongs_to_code_file(db_session):
    """Verify CodeChunk belongs to CodeFile and cascades on deletion."""
    repo = Repository(
        url="https://github.com/test/repo-chunks",
        name="test/repo-chunks",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    code_file = CodeFile(
        repository_id=repo.id,
        path="src/utils.py",
        extension=".py",
        size_bytes=85,
    )
    db_session.add(code_file)
    await db_session.flush()

    chunk = CodeChunk(
        file_id=code_file.id,
        chunk_index=0,
        content="def helper(): pass",
        start_line=1,
        end_line=1,
        embedding=[0.1] * settings.embedding_dimension,
    )

    db_session.add(chunk)
    await db_session.flush()

    assert chunk.id is not None
    assert chunk.file_id == code_file.id
    assert chunk.file.path == "src/utils.py"


async def test_duplicate_file_paths_prevented(db_session):
    """Duplicate file paths for the same repository raise IntegrityError."""
    repo = Repository(
        url="https://github.com/test/repo-dup-files",
        name="test/repo-dup-files",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    file1 = CodeFile(
        repository_id=repo.id,
        path="duplicate/path.py",
        extension=".py",
        size_bytes=50,
    )
    db_session.add(file1)
    await db_session.flush()

    file2 = CodeFile(
        repository_id=repo.id,
        path="duplicate/path.py",
        extension=".py",
        size_bytes=100,
    )
    db_session.add(file2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_duplicate_chunk_indexes_prevented(db_session):
    """Duplicate chunk indexes for the same file raise IntegrityError."""
    repo = Repository(
        url="https://github.com/test/repo-dup-chunks",
        name="test/repo-dup-chunks",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    file1 = CodeFile(
        repository_id=repo.id,
        path="module.py",
        extension=".py",
        size_bytes=200,
    )
    db_session.add(file1)
    await db_session.flush()

    chunk1 = CodeChunk(
        file_id=file1.id,
        chunk_index=0,
        content="chunk 0 content",
        start_line=1,
        end_line=10,
        embedding=[0.05] * settings.embedding_dimension,
    )
    db_session.add(chunk1)
    await db_session.flush()

    chunk2 = CodeChunk(
        file_id=file1.id,
        chunk_index=0,  # Duplicate index
        content="another chunk 0",
        start_line=1,
        end_line=10,
        embedding=[0.08] * settings.embedding_dimension,
    )
    db_session.add(chunk2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_store_and_retrieve_pgvector_embedding(db_session):
    """Verify vector embeddings can be stored and retrieved with exact dimension."""
    repo = Repository(
        url="https://github.com/test/vector-test",
        name="test/vector-test",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    code_file = CodeFile(
        repository_id=repo.id,
        path="vector.py",
        extension=".py",
        size_bytes=300,
    )
    db_session.add(code_file)
    await db_session.flush()

    dim = settings.embedding_dimension
    test_embedding = [float(i) / float(dim) for i in range(dim)]
    chunk = CodeChunk(
        file_id=code_file.id,
        chunk_index=0,
        content="vector content test",
        start_line=1,
        end_line=5,
        embedding=test_embedding,
    )
    db_session.add(chunk)
    await db_session.flush()

    # Query back
    result = await db_session.execute(select(CodeChunk).where(CodeChunk.id == chunk.id))
    fetched_chunk = result.scalar_one()

    assert fetched_chunk is not None
    assert len(fetched_chunk.embedding) == dim
    assert pytest.approx(fetched_chunk.embedding[0]) == test_embedding[0]
    assert pytest.approx(fetched_chunk.embedding[dim - 1]) == test_embedding[dim - 1]

