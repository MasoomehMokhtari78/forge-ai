"""
Tests for RetrievalService: pgvector similarity ranking, repository isolation, and lifecycle guards.
"""

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.services.embedding import MockEmbeddingService
from app.services.retrieval import (
    RepositoryNotFoundError,
    RepositoryNotReadyForSearchError,
    RetrievalService,
)


@pytest.fixture
def mock_embedding_service():
    return MockEmbeddingService(dimension=settings.embedding_dimension)


@pytest.fixture
def retrieval_service(mock_embedding_service):
    return RetrievalService(embedding_service=mock_embedding_service)


async def _create_test_repo(
    db: AsyncSession,
    name: str = "test/repo",
    status: IngestionStatus = IngestionStatus.COMPLETED,
) -> Repository:
    repo = Repository(
        url=f"https://github.com/{name}-{uuid4().hex[:6]}",
        name=name,
        status=status,
    )
    db.add(repo)
    await db.flush()
    return repo


async def _add_chunk(
    db: AsyncSession,
    repo_id,
    path: str,
    content: str,
    start_line: int,
    end_line: int,
    embedding: list[float],
    chunk_index: int = 0,
) -> CodeChunk:
    code_file = CodeFile(
        repository_id=repo_id,
        path=path,
        extension=".py",
        size_bytes=len(content.encode("utf-8")),
    )
    db.add(code_file)
    await db.flush()

    chunk = CodeChunk(
        file_id=code_file.id,
        chunk_index=chunk_index,
        content=content,
        start_line=start_line,
        end_line=end_line,
        embedding=embedding,
    )
    db.add(chunk)
    await db.flush()
    return chunk


# ===========================================================================
# 1. Mathematical Correctness & Ranking
# ===========================================================================

async def test_retrieval_ranks_by_cosine_similarity(db_session, retrieval_service, mock_embedding_service):
    """Chunks closer to the query vector must rank first with mathematically correct similarity in [0, 1]."""
    repo = await _create_test_repo(db_session)

    # Generate distinct embeddings
    query_text = "jwt authentication token verification"
    embeddings = await mock_embedding_service.get_embeddings([
        query_text,
        "jwt authentication token verification",  # exact match
        "unrelated database migration script",     # distinct
    ])

    exact_emb = embeddings[1]
    unrelated_emb = embeddings[2]

    await _add_chunk(db_session, repo.id, "src/auth.py", "def verify_token(): pass", 1, 10, exact_emb)
    await _add_chunk(db_session, repo.id, "src/db.py", "def run_migration(): pass", 1, 10, unrelated_emb)

    results = await retrieval_service.search(
        repository_id=repo.id,
        query=query_text,
        db=db_session,
        top_k=5,
    )

    assert len(results) == 2
    # Exact match should have similarity approx 1.0 (cosine distance ~ 0)
    assert results[0].path == "src/auth.py"
    assert results[0].similarity > results[1].similarity
    assert pytest.approx(results[0].similarity, rel=1e-3) == 1.0
    assert 0.0 <= results[1].similarity <= 1.0


async def test_retrieval_top_k_limiting(db_session, retrieval_service, mock_embedding_service):
    """top_k limit is enforced at the database level."""
    repo = await _create_test_repo(db_session)

    texts = [f"function snippet {i}" for i in range(6)]
    embeddings = await mock_embedding_service.get_embeddings(texts)

    for i in range(5):
        await _add_chunk(
            db_session,
            repo.id,
            f"src/file_{i}.py",
            f"code content {i}",
            1,
            10,
            embeddings[i],
        )

    results = await retrieval_service.search(
        repository_id=repo.id,
        query="function snippet",
        db=db_session,
        top_k=3,
    )

    assert len(results) == 3


async def test_retrieval_similarity_threshold(db_session, retrieval_service, mock_embedding_service):
    """similarity_threshold filters out chunks below the threshold."""
    repo = await _create_test_repo(db_session)

    embeddings = await mock_embedding_service.get_embeddings([
        "search query",
        "search query",     # exact (sim ~ 1.0)
        "completely different semantic topic",  # lower sim
    ])

    await _add_chunk(db_session, repo.id, "match.py", "exact match", 1, 5, embeddings[1])
    await _add_chunk(db_session, repo.id, "diff.py", "different content", 1, 5, embeddings[2])

    # With high threshold (e.g. 0.95), only exact match should be returned
    results = await retrieval_service.search(
        repository_id=repo.id,
        query="search query",
        db=db_session,
        top_k=5,
        similarity_threshold=0.95,
    )

    assert len(results) == 1
    assert results[0].path == "match.py"


# ===========================================================================
# 2. Critical Security Invariant: Repository Isolation
# ===========================================================================

async def test_repository_isolation_never_leaks_chunks_across_repos(
    db_session,
    retrieval_service,
    mock_embedding_service,
):
    """A search in Repository A must NEVER return chunks belonging to Repository B,

    even if Repository B's chunk is an exact match for the query.
    """
    repo_a = await _create_test_repo(db_session, name="org/repo-a")
    repo_b = await _create_test_repo(db_session, name="org/repo-b")

    query = "critical secret algorithm"
    embeddings = await mock_embedding_service.get_embeddings([
        query,
        query,                   # exact match embedding
        "unrelated content a",   # chunk in repo A
    ])

    # Repo B has the exact matching chunk
    await _add_chunk(db_session, repo_b.id, "repo_b/secret.py", "exact secret code", 1, 20, embeddings[1])

    # Repo A has an unrelated chunk
    await _add_chunk(db_session, repo_a.id, "repo_a/main.py", "repo a code", 1, 10, embeddings[2])

    # Query Repository A: must NOT return repo B's chunk
    results_a = await retrieval_service.search(
        repository_id=repo_a.id,
        query=query,
        db=db_session,
        top_k=10,
    )

    assert len(results_a) == 1
    assert results_a[0].path == "repo_a/main.py"
    assert all("repo_b" not in r.path for r in results_a)

    # Query Repository B: returns repo B's chunk only
    results_b = await retrieval_service.search(
        repository_id=repo_b.id,
        query=query,
        db=db_session,
        top_k=10,
    )
    assert len(results_b) == 1
    assert results_b[0].path == "repo_b/secret.py"


# ===========================================================================
# 3. Repository Status & Lifecycle Guards
# ===========================================================================

async def test_retrieval_non_existent_repository_raises_not_found(db_session, retrieval_service):
    """Searching a non-existent repository UUID raises RepositoryNotFoundError."""
    with pytest.raises(RepositoryNotFoundError, match="not found"):
        await retrieval_service.search(
            repository_id=uuid4(),
            query="test",
            db=db_session,
        )


async def test_retrieval_uncompleted_repository_raises_not_ready(db_session, retrieval_service):
    """Searching a repository that is still PENDING or FAILED raises RepositoryNotReadyForSearchError."""
    pending_repo = await _create_test_repo(db_session, status=IngestionStatus.PENDING)

    with pytest.raises(RepositoryNotReadyForSearchError, match="Ingestion must be completed"):
        await retrieval_service.search(
            repository_id=pending_repo.id,
            query="test",
            db=db_session,
        )


async def test_retrieval_empty_or_unindexed_repository_returns_empty_list(
    db_session,
    retrieval_service,
):
    """A COMPLETED repository that has no indexed chunks returns an empty list without error."""
    empty_repo = await _create_test_repo(db_session, status=IngestionStatus.COMPLETED)

    results = await retrieval_service.search(
        repository_id=empty_repo.id,
        query="any query",
        db=db_session,
    )

    assert results == []
