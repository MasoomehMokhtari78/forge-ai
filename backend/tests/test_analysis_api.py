"""
API integration tests for Knowledge-Guided Analysis (POST /analysis/knowledge).
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.analysis import get_analysis_service
from app.main import app as fastapi_app
from app.schemas.analysis import AnalysisResponse, AnalysisSource
from app.services.knowledge_guided_analysis import (
    AnalysisKnowledgeNotFoundError,
    AnalysisKnowledgeNotReadyError,
    AnalysisRepositoryNotFoundError,
    AnalysisRepositoryNotReadyError,
    FileNotFoundInRepositoryError,
    KnowledgeGuidedAnalysisService,
)


@pytest.fixture
def mock_analysis_service():
    service = AsyncMock(spec=KnowledgeGuidedAnalysisService)
    fastapi_app.dependency_overrides[get_analysis_service] = lambda: service
    yield service
    fastapi_app.dependency_overrides.pop(get_analysis_service, None)


def test_api_analysis_successful(client: TestClient, mock_analysis_service):
    """POST /analysis/knowledge returns 200 with answer and verified sources."""
    repo_id = uuid4()
    knowledge_id = uuid4()

    mock_analysis_service.analyze.return_value = AnalysisResponse(
        answer="[MOCK LLM RESPONSE] OrderService can be refactored using Command pattern.",
        sources=[
            AnalysisSource(
                source_id="src_1",
                type="repository",
                label="src/order.py:1-10",
                path="src/order.py",
                start_line=1,
                end_line=10,
            ),
            AnalysisSource(
                source_id="src_2",
                type="knowledge",
                label="patterns.pdf, page 14",
                path="patterns.pdf",
                page_number=14,
            ),
        ],
    )

    payload = {
        "repository_id": str(repo_id),
        "knowledge_id": str(knowledge_id),
        "code_scope": {"type": "repository"},
        "question": "What pattern would improve the order processing architecture?",
    }

    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert "Command pattern" in data["answer"]
    assert len(data["sources"]) == 2
    types = {s["type"] for s in data["sources"]}
    assert "repository" in types
    assert "knowledge" in types


def test_api_analysis_file_scoped(client: TestClient, mock_analysis_service):
    """POST /analysis/knowledge with file code_scope targets specifically that file."""
    repo_id = uuid4()
    knowledge_id = uuid4()

    mock_analysis_service.analyze.return_value = AnalysisResponse(
        answer="[MOCK LLM RESPONSE] Gateway analysis complete.",
        sources=[
            AnalysisSource(
                source_id="src_1",
                type="repository",
                label="src/gateway.py:1-15",
                path="src/gateway.py",
                start_line=1,
                end_line=15,
            ),
            AnalysisSource(
                source_id="src_2",
                type="knowledge",
                label="microservices.pdf, page 33",
                path="microservices.pdf",
                page_number=33,
            ),
        ],
    )

    payload = {
        "repository_id": str(repo_id),
        "knowledge_id": str(knowledge_id),
        "code_scope": {"type": "file", "path": "src/gateway.py"},
        "question": "Evaluate this gateway implementation.",
    }

    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    repo_sources = [s for s in data["sources"] if s["type"] == "repository"]
    assert len(repo_sources) == 1
    assert repo_sources[0]["path"] == "src/gateway.py"


def test_api_analysis_repo_not_found(client: TestClient, mock_analysis_service):
    """POST /analysis/knowledge with unknown repository returns 404."""
    repo_id = uuid4()
    mock_analysis_service.analyze.side_effect = AnalysisRepositoryNotFoundError(
        f"Repository '{repo_id}' not found."
    )

    payload = {
        "repository_id": str(repo_id),
        "knowledge_id": str(uuid4()),
        "code_scope": {"type": "repository"},
        "question": "Any question",
    }
    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 404
    assert f"Repository '{repo_id}' not found" in resp.json()["detail"]


def test_api_analysis_knowledge_not_found(client: TestClient, mock_analysis_service):
    """POST /analysis/knowledge with unknown knowledge scope returns 404."""
    knowledge_id = uuid4()
    mock_analysis_service.analyze.side_effect = AnalysisKnowledgeNotFoundError(
        f"Engineering knowledge scope '{knowledge_id}' not found."
    )

    payload = {
        "repository_id": str(uuid4()),
        "knowledge_id": str(knowledge_id),
        "code_scope": {"type": "repository"},
        "question": "Any question",
    }
    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 404
    assert f"Engineering knowledge scope '{knowledge_id}' not found" in resp.json()["detail"]


def test_api_analysis_file_not_found_in_repository(client: TestClient, mock_analysis_service):
    """POST /analysis/knowledge with file not in repository returns 404."""
    mock_analysis_service.analyze.side_effect = FileNotFoundInRepositoryError(
        "File 'does_not_exist.py' was not found in repository."
    )

    payload = {
        "repository_id": str(uuid4()),
        "knowledge_id": str(uuid4()),
        "code_scope": {"type": "file", "path": "does_not_exist.py"},
        "question": "Analyze missing file",
    }
    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 404
    assert "was not found in repository" in resp.json()["detail"]


def test_api_analysis_repo_not_ready(client: TestClient, mock_analysis_service):
    """POST /analysis/knowledge with unready repository returns 400."""
    mock_analysis_service.analyze.side_effect = AnalysisRepositoryNotReadyError(
        "Repository ingestion status is 'pending'. Must be completed."
    )

    payload = {
        "repository_id": str(uuid4()),
        "knowledge_id": str(uuid4()),
        "code_scope": {"type": "repository"},
        "question": "Analyze pending repo",
    }
    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 400
    assert "Must be completed" in resp.json()["detail"]


def test_api_analysis_knowledge_not_ready(client: TestClient, mock_analysis_service):
    """POST /analysis/knowledge with failed knowledge scope returns 400."""
    mock_analysis_service.analyze.side_effect = AnalysisKnowledgeNotReadyError(
        "Engineering knowledge scope is in a FAILED state."
    )

    payload = {
        "repository_id": str(uuid4()),
        "knowledge_id": str(uuid4()),
        "code_scope": {"type": "repository"},
        "question": "Analyze failed knowledge",
    }
    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 400
    assert "FAILED state" in resp.json()["detail"]


def test_api_analysis_invalid_scope_type(client: TestClient):
    """POST /analysis/knowledge with invalid scope type returns 422 Unprocessable Entity."""
    payload = {
        "repository_id": str(uuid4()),
        "knowledge_id": str(uuid4()),
        "code_scope": {"type": "invalid_type"},
        "question": "Any question",
    }
    resp = client.post("/analysis/knowledge", json=payload)
    assert resp.status_code == 422
