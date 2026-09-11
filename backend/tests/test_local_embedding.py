"""
Tests for LocalEmbeddingService and local embedding model execution.
"""

import math
from pathlib import Path
from uuid import uuid4

import pytest
import torch

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.services.embedding import (
    EmbeddingError,
    LocalEmbeddingService,
    resolve_embedding_device,
)
from app.services.repository_indexing import RepositoryIndexingService


# ===========================================================================
# 1. Device Resolution Tests
# ===========================================================================

def test_resolve_device_cpu():
    """Explicit 'cpu' setting resolves to 'cpu'."""
    assert resolve_embedding_device("cpu") == "cpu"
    assert resolve_embedding_device("CPU") == "cpu"


def test_resolve_device_auto():
    """'auto' selects 'cuda' if torch.cuda.is_available(), otherwise 'cpu'."""
    expected = "cuda" if torch.cuda.is_available() else "cpu"
    assert resolve_embedding_device("auto") == expected
    assert resolve_embedding_device("AUTO") == expected


def test_resolve_device_cuda_explicit():
    """'cuda' resolves to 'cuda' when available, or raises RuntimeError when unavailable."""
    if torch.cuda.is_available():
        assert resolve_embedding_device("cuda") == "cuda"
    else:
        with pytest.raises(RuntimeError, match="CUDA is explicitly configured"):
            resolve_embedding_device("cuda")


def test_resolve_device_invalid():
    """Invalid device string raises ValueError."""
    with pytest.raises(ValueError, match="Invalid EMBEDDING_DEVICE"):
        resolve_embedding_device("invalid_device")


# ===========================================================================
# 2. LocalEmbeddingService Unit Tests
# ===========================================================================

@pytest.fixture(scope="module")
def local_embedding_service():
    """Module-scoped service so the model is loaded only once for this test module."""
    return LocalEmbeddingService(
        model_name="BAAI/bge-small-en-v1.5",
        dimension=384,
        device="cpu",
    )


def test_local_service_configured_dimension(local_embedding_service):
    """Local embedding service reports the configured dimension (384)."""
    assert local_embedding_service.dimension == 384


async def test_single_text_embedding(local_embedding_service):
    """A single input text produces a single embedding of exact dimension 384."""
    texts = ["def calculate_fibonacci(n): return n if n <= 1 else calculate_fibonacci(n-1) + calculate_fibonacci(n-2)"]
    embeddings = await local_embedding_service.get_embeddings(texts)

    assert len(embeddings) == 1
    assert len(embeddings[0]) == 384

    # Verify elements are valid finite floats and vector is normalized (L2 norm ~ 1.0)
    vec = embeddings[0]
    assert all(isinstance(x, float) and not math.isnan(x) and not math.isinf(x) for x in vec)
    norm = math.sqrt(sum(x * x for x in vec))
    assert pytest.approx(norm, rel=1e-3) == 1.0


async def test_multiple_texts_and_batching(local_embedding_service):
    """Multiple texts produce the corresponding number of embeddings in proper order."""
    texts = [
        "import os\nimport sys",
        "class CodeFile:\n    pass",
        "def main():\n    print('hello world')",
        "export const sum = (a: number, b: number) => a + b;",
    ]

    embeddings = await local_embedding_service.get_embeddings(texts)

    assert len(embeddings) == len(texts)
    for vec in embeddings:
        assert len(vec) == 384
        assert all(isinstance(x, float) for x in vec)


async def test_empty_input_returns_empty_list(local_embedding_service):
    """Empty list of texts returns empty list without calling model."""
    assert await local_embedding_service.get_embeddings([]) == []


# ===========================================================================
# 3. End-to-End Indexing with LocalEmbeddingService
# ===========================================================================

async def test_indexing_with_local_embedding_service(db_session, tmp_path: Path, local_embedding_service):
    """Verify full indexing pipeline using real local sentence-transformers inference."""
    repo = Repository(
        url="https://github.com/test/local-embed-repo",
        name="test/local-embed-repo",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    repo_dir = tmp_path / str(repo.id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "index.py").write_text("def run():\n    return 42\n", encoding="utf-8")
    (repo_dir / "README.md").write_text("# Local Embeddings Test\nWorking locally without API keys.\n", encoding="utf-8")

    service = RepositoryIndexingService(embedding_service=local_embedding_service)
    service.storage_root = tmp_path

    result = await service.index_repository(repository_id=repo.id, db=db_session)

    assert result.files_indexed == 2
    assert result.chunks_created == 2

    # Verify stored chunks in database have vector dimension 384
    from sqlalchemy import select
    chunks_query = select(CodeChunk).join(CodeFile).where(CodeFile.repository_id == repo.id)
    db_chunks = list((await db_session.execute(chunks_query)).scalars().all())

    assert len(db_chunks) == 2
    for chunk in db_chunks:
        assert len(chunk.embedding) == 384
        assert isinstance(chunk.embedding[0], float)

    # Verify re-indexing idempotency with local embedding service
    reindex_result = await service.index_repository(repository_id=repo.id, db=db_session)
    assert reindex_result.files_indexed == 2
    assert reindex_result.chunks_created == 2

    db_chunks_after = list((await db_session.execute(chunks_query)).scalars().all())
    assert len(db_chunks_after) == 2
