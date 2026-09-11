"""
Tests for RepositoryIndexingService.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.services.embedding import EmbeddingError, MockEmbeddingService
from app.core.config import settings
from app.services.repository_indexing import (
    IndexingError,
    RepositoryFilesNotAvailableError,
    RepositoryIndexingService,
    RepositoryNotFoundError,
    RepositoryNotReadyForIndexingError,
)


@pytest.fixture
def mock_embedding_service():
    return MockEmbeddingService(dimension=settings.embedding_dimension)



async def test_index_small_repository_success(db_session, tmp_path: Path, mock_embedding_service):
    """Verify that a repository with eligible source files is indexed properly."""
    repo = Repository(
        url="https://github.com/test/index-success",
        name="test/index-success",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    # Create files on disk under tmp_path/<repo.id>
    repo_dir = tmp_path / str(repo.id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "main.py").write_text("def main():\n    print('hello')\n", encoding="utf-8")
    (repo_dir / "README.md").write_text("# My Repo\nDescription here\n", encoding="utf-8")

    # Create ignored files (should not be indexed)
    (repo_dir / ".git").mkdir()
    (repo_dir / ".git" / "config").write_text("git config", encoding="utf-8")
    (repo_dir / "node_modules").mkdir()
    (repo_dir / "node_modules" / "dep.js").write_text("module.exports = {}", encoding="utf-8")
    (repo_dir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    service = RepositoryIndexingService(embedding_service=mock_embedding_service)
    service.storage_root = tmp_path

    result = await service.index_repository(repository_id=repo.id, db=db_session)

    assert result.repository_id == repo.id
    assert result.files_indexed == 2  # src/main.py, README.md
    assert result.chunks_created >= 2

    # Verify records in database
    files_result = await db_session.execute(
        select(CodeFile).where(CodeFile.repository_id == repo.id).order_by(CodeFile.path)
    )
    db_files = list(files_result.scalars().all())
    assert len(db_files) == 2
    paths = [f.path for f in db_files]
    assert paths == ["README.md", "src/main.py"]

    # Verify no ignored files in database
    assert not any(".git" in p or "node_modules" in p or "image.png" in p for p in paths)

    # Verify chunks
    chunks_result = await db_session.execute(
        select(CodeChunk).join(CodeFile).where(CodeFile.repository_id == repo.id)
    )
    db_chunks = list(chunks_result.scalars().all())
    assert len(db_chunks) == result.chunks_created
    for chunk in db_chunks:
        assert len(chunk.embedding) == settings.embedding_dimension



async def test_reindexing_is_idempotent(db_session, tmp_path: Path, mock_embedding_service):
    """Re-indexing replaces previous files and chunks without creating duplicates."""
    repo = Repository(
        url="https://github.com/test/idempotent-repo",
        name="test/idempotent-repo",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    repo_dir = tmp_path / str(repo.id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "file1.py").write_text("x = 10\n", encoding="utf-8")

    service = RepositoryIndexingService(embedding_service=mock_embedding_service)
    service.storage_root = tmp_path

    # First indexing run
    res1 = await service.index_repository(repository_id=repo.id, db=db_session)
    assert res1.files_indexed == 1
    assert res1.chunks_created == 1

    # Second indexing run (e.g. after modifying file)
    (repo_dir / "file1.py").write_text("x = 20\ny = 30\n", encoding="utf-8")
    res2 = await service.index_repository(repository_id=repo.id, db=db_session)
    assert res2.files_indexed == 1
    assert res2.chunks_created == 1

    # Verify database has exactly 1 file and 1 chunk (not 2)
    files_count = (
        await db_session.execute(select(func.count()).select_from(CodeFile).where(CodeFile.repository_id == repo.id))
    ).scalar_one()
    chunks_count = (
        await db_session.execute(
            select(func.count()).select_from(CodeChunk).join(CodeFile).where(CodeFile.repository_id == repo.id)
        )
    ).scalar_one()

    assert files_count == 1
    assert chunks_count == 1


async def test_indexing_failure_rolls_back_consistently(db_session, tmp_path: Path):
    """If embedding generation fails, no partial files or chunks remain in the database."""
    repo = Repository(
        url="https://github.com/test/fail-rollback",
        name="test/fail-rollback",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    repo_dir = tmp_path / str(repo.id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "main.py").write_text("print(1)\n", encoding="utf-8")

    failing_embedding_service = AsyncMock()
    failing_embedding_service.dimension = settings.embedding_dimension
    failing_embedding_service.get_embeddings.side_effect = EmbeddingError("API connection error")


    service = RepositoryIndexingService(embedding_service=failing_embedding_service)
    service.storage_root = tmp_path

    with pytest.raises(IndexingError):
        await service.index_repository(repository_id=repo.id, db=db_session)

    # Verify no files or chunks exist in database
    files_count = (
        await db_session.execute(select(func.count()).select_from(CodeFile).where(CodeFile.repository_id == repo.id))
    ).scalar_one()
    assert files_count == 0


async def test_index_uncompleted_repository_rejected(db_session, tmp_path: Path, mock_embedding_service):
    """Indexing a repository that is still PENDING or FAILED raises RepositoryNotReadyForIndexingError."""
    repo = Repository(
        url="https://github.com/test/pending-repo",
        name="test/pending-repo",
        status=IngestionStatus.PENDING,
    )
    db_session.add(repo)
    await db_session.flush()

    service = RepositoryIndexingService(embedding_service=mock_embedding_service)
    service.storage_root = tmp_path

    with pytest.raises(RepositoryNotReadyForIndexingError):
        await service.index_repository(repository_id=repo.id, db=db_session)


async def test_index_missing_local_files_rejected(db_session, tmp_path: Path, mock_embedding_service):
    """If the local cloned directory is missing, raises RepositoryFilesNotAvailableError."""
    repo = Repository(
        url="https://github.com/test/missing-files-repo",
        name="test/missing-files-repo",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    service = RepositoryIndexingService(embedding_service=mock_embedding_service)
    service.storage_root = tmp_path  # Directory for repo.id is NOT created

    with pytest.raises(RepositoryFilesNotAvailableError):
        await service.index_repository(repository_id=repo.id, db=db_session)
