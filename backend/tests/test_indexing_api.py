"""
API tests for repository indexing endpoints (POST and GET /repositories/{id}/index).
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.api.repositories import get_indexing_service
from app.core.config import settings
from app.main import app as fastapi_app
from app.models.repository import IngestionStatus, Repository
from app.services.embedding import MockEmbeddingService
from app.services.repository_indexing import RepositoryIndexingService


@pytest.fixture
def mock_indexing_service(tmp_path: Path):
    service = RepositoryIndexingService(embedding_service=MockEmbeddingService(dimension=settings.embedding_dimension))
    service.storage_root = tmp_path
    return service



def test_api_index_non_existent_repository_returns_404(client, mock_indexing_service):
    """Indexing a non-existent repository UUID returns 404 Not Found."""
    fastapi_app.dependency_overrides[get_indexing_service] = lambda: mock_indexing_service
    fake_id = uuid4()

    res = client.post(f"/repositories/{fake_id}/index")
    assert res.status_code == 404
    assert f"Repository with ID '{fake_id}' not found" in res.json()["detail"]


def test_api_index_uncompleted_repository_returns_400(client, tmp_path: Path, mock_indexing_service):
    """Indexing a repository that is still PENDING or FAILED returns 400 Bad Request."""
    fastapi_app.dependency_overrides[get_indexing_service] = lambda: mock_indexing_service

    # Create a repository with PENDING status
    post_res = client.post("/repositories", json={"url": "https://github.com/mock/pending-index-test"})
    # Mock cloner failure to leave it in FAILED status, or mock to leave PENDING
    repo_id = post_res.json()["id"]

    # The repo was cloned or failed. Let's test calling /index
    res = client.post(f"/repositories/{repo_id}/index")
    # If status is failed, it must return 400
    assert res.status_code == 400
    assert "Ingestion must be completed before indexing" in res.json()["detail"]


def test_api_index_successful(client, tmp_path: Path):
    """Successful indexing returns 200 with repository_id, status, files_indexed, chunks_created."""
    # 1. Ingest a repository successfully with mocked cloner
    target_url = "https://github.com/mock-indexer/sample-repo"

    async def mock_clone(url: str, repo_id):
        repo_dir = tmp_path / str(repo_id)
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n", encoding="utf-8")
        (repo_dir / "config.py").write_text("PORT = 8080\n", encoding="utf-8")
        return repo_dir

    with patch("app.services.repository_ingestion.RepositoryCloner") as MockClonerClass:
        mock_cloner = MockClonerClass.return_value
        mock_cloner.clone = AsyncMock(side_effect=mock_clone)
        mock_cloner.cleanup = AsyncMock()

        ingest_res = client.post("/repositories", json={"url": target_url})
        assert ingest_res.status_code == 201
        repo_id = ingest_res.json()["id"]

    # 2. Trigger indexing with mock embedding service
    indexing_service = RepositoryIndexingService(embedding_service=MockEmbeddingService(dimension=settings.embedding_dimension))
    indexing_service.storage_root = tmp_path
    fastapi_app.dependency_overrides[get_indexing_service] = lambda: indexing_service

    index_res = client.post(f"/repositories/{repo_id}/index")
    assert index_res.status_code == 200
    data = index_res.json()

    assert data["repository_id"] == repo_id
    assert data["status"] == "completed"
    assert data["files_indexed"] == 2
    assert data["chunks_created"] >= 2

    # 3. Query index summary via GET /repositories/{id}/index
    summary_res = client.get(f"/repositories/{repo_id}/index")
    assert summary_res.status_code == 200
    summary_data = summary_res.json()
    assert summary_data["repository_id"] == repo_id
    assert summary_data["files_indexed"] == 2
    assert summary_data["chunks_created"] == data["chunks_created"]
