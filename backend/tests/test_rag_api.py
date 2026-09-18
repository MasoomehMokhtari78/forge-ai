"""
API tests for semantic search (POST /repositories/{id}/search) and RAG chat (POST /repositories/{id}/chat).
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api.repositories import get_rag_service, get_retrieval_service
from app.main import app as fastapi_app
from app.models.repository import IngestionStatus, Repository
from app.schemas.rag import ChatResponse, ChunkRetrievalResult, Citation
from app.services.rag import RAGService
from app.services.retrieval import RetrievalService


@pytest.fixture
def mock_retrieval_service():
    return AsyncMock(spec=RetrievalService)


@pytest.fixture
def mock_rag_service():
    return AsyncMock(spec=RAGService)


# ===========================================================================
# 1. /repositories/{id}/search API Tests
# ===========================================================================

def test_api_search_successful(client, mock_retrieval_service):
    """POST /repositories/{id}/search returns 200 with ranked search results."""
    repo_id = uuid4()
    chunk_id = uuid4()
    file_id = uuid4()

    mock_retrieval_service.search.return_value = [
        ChunkRetrievalResult(
            chunk_id=chunk_id,
            file_id=file_id,
            path="src/service.py",
            content="class Service: pass",
            start_line=1,
            end_line=5,
            similarity=0.92,
        )
    ]
    fastapi_app.dependency_overrides[get_retrieval_service] = lambda: mock_retrieval_service

    payload = {"query": "service definition", "top_k": 5, "similarity_threshold": 0.5}
    res = client.post(f"/repositories/{repo_id}/search", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["repository_id"] == str(repo_id)
    assert data["query"] == "service definition"
    assert len(data["results"]) == 1
    assert data["results"][0]["path"] == "src/service.py"
    assert data["results"][0]["similarity"] == 0.92


def test_api_search_non_existent_repo_returns_404(client):
    """POST /repositories/{id}/search on non-existent repository returns 404."""
    # Use real service with database dependency to test actual 404 handling
    fake_id = uuid4()
    res = client.post(f"/repositories/{fake_id}/search", json={"query": "test"})
    assert res.status_code == 404
    assert f"Repository with ID '{fake_id}' not found" in res.json()["detail"]


def test_api_search_uncompleted_repo_returns_400(client, tmp_path):
    """POST /repositories/{id}/search on PENDING or FAILED repository returns 400."""
    # Ingest a repository (starts PENDING/FAILED when mock cloner fails)
    create_res = client.post("/repositories", json={"url": "https://github.com/test/pending-search"})
    assert create_res.status_code == 201
    repo_id = create_res.json()["id"]

    # Since cloner was not mocked, it failed and status is FAILED
    res = client.post(f"/repositories/{repo_id}/search", json={"query": "test"})
    assert res.status_code == 400
    assert "Ingestion must be completed" in res.json()["detail"]


def test_api_search_validation_errors(client):
    """Invalid query or top_k returns 422 Unprocessable Entity."""
    repo_id = uuid4()

    # Empty query
    res = client.post(f"/repositories/{repo_id}/search", json={"query": ""})
    assert res.status_code == 422

    # top_k < 1
    res = client.post(f"/repositories/{repo_id}/search", json={"query": "valid", "top_k": 0})
    assert res.status_code == 422

    # top_k > 50
    res = client.post(f"/repositories/{repo_id}/search", json={"query": "valid", "top_k": 51})
    assert res.status_code == 422


# ===========================================================================
# 2. /repositories/{id}/chat API Tests
# ===========================================================================

def test_api_chat_successful(client, mock_rag_service):
    """POST /repositories/{id}/chat returns 200 with answer and programmatic sources."""
    repo_id = uuid4()
    mock_rag_service.answer_question.return_value = ChatResponse(
        answer="[MOCK LLM RESPONSE] Authentication is handled via JWT tokens.",
        sources=[Citation(path="src/auth.py", start_line=1, end_line=25)],
    )
    fastapi_app.dependency_overrides[get_rag_service] = lambda: mock_rag_service

    payload = {"question": "How is authentication handled?"}
    res = client.post(f"/repositories/{repo_id}/chat", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert "JWT tokens" in data["answer"]
    assert len(data["sources"]) == 1
    assert data["sources"][0]["path"] == "src/auth.py"
    assert data["sources"][0]["start_line"] == 1
    assert data["sources"][0]["end_line"] == 25


def test_api_chat_non_existent_repo_returns_404(client):
    """POST /repositories/{id}/chat on non-existent repository returns 404."""
    fake_id = uuid4()
    res = client.post(f"/repositories/{fake_id}/chat", json={"question": "Where is main?"})
    assert res.status_code == 404
    assert f"Repository with ID '{fake_id}' not found" in res.json()["detail"]


def test_api_chat_validation_errors(client):
    """Empty question returns 422 Unprocessable Entity."""
    repo_id = uuid4()
    res = client.post(f"/repositories/{repo_id}/chat", json={"question": ""})
    assert res.status_code == 422
