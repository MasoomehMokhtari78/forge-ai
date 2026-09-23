"""
API tests for POST /repositories/{id}/agent endpoint.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.api.repositories import get_agent_service
from app.main import app as fastapi_app
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.agent import (
    AgentResponse,
    AgentStatus,
    SourceCitation,
    ToolActivitySummary,
    ToolName,
)
from app.services.agent import AgentService
from app.services.agent_tools import AgentTools


@pytest.fixture
def mock_agent_service():
    return AsyncMock(spec=AgentService)


def test_api_agent_successful(client, mock_agent_service):
    """POST /repositories/{id}/agent returns 200 with answer, verified sources, and safe activity."""
    repo_id = uuid4()

    mock_agent_service.run.return_value = AgentResponse(
        answer="[MOCK AGENT] Authentication uses JWT middleware.",
        sources=[
            SourceCitation(
                source_id="src_1",
                path="src/auth.py",
                start_line=1,
                end_line=25,
                source_type="read",
            )
        ],
        status=AgentStatus.COMPLETED,
        tool_calls_count=2,
        iterations_count=3,
        tool_activity=[
            ToolActivitySummary(
                execution_order=1,
                tool=ToolName.SEARCH_CODE,
                parameters={"query": "auth"},
                success=True,
                summary="Found 1 matching code chunk.",
            ),
            ToolActivitySummary(
                execution_order=2,
                tool=ToolName.READ_FILE,
                parameters={"path": "src/auth.py", "lines": "1-25"},
                success=True,
                summary="Read 25 lines from src/auth.py.",
            ),
        ],
    )
    fastapi_app.dependency_overrides[get_agent_service] = lambda: mock_agent_service

    payload = {"question": "How does authentication work?", "max_iterations": 5}
    res = client.post(f"/repositories/{repo_id}/agent", json=payload)

    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "completed"
    assert "JWT middleware" in data["answer"]
    assert data["tool_calls_count"] == 2
    assert len(data["sources"]) == 1
    assert data["sources"][0]["source_id"] == "src_1"
    assert data["sources"][0]["path"] == "src/auth.py"
    assert len(data["tool_activity"]) == 2
    assert data["tool_activity"][0]["tool"] == "search_code"


def test_api_agent_non_existent_repo_returns_404(client):
    """POST /repositories/{id}/agent on non-existent repository returns 404."""
    fake_id = uuid4()
    res = client.post(f"/repositories/{fake_id}/agent", json={"question": "Where is main?"})
    assert res.status_code == 404
    assert f"Repository with ID '{fake_id}' not found" in res.json()["detail"]


def test_api_agent_uncompleted_repo_returns_400(client):
    """POST /repositories/{id}/agent on PENDING or FAILED repository returns 400."""
    create_res = client.post("/repositories", json={"url": "https://github.com/test/pending-agent"})
    assert create_res.status_code == 201
    repo_id = create_res.json()["id"]

    res = client.post(f"/repositories/{repo_id}/agent", json={"question": "Analyze repo"})
    assert res.status_code == 400
    assert "Ingestion must be completed" in res.json()["detail"]


def test_api_agent_unindexed_repo_returns_400(client, tmp_path):
    """POST /repositories/{id}/agent on a COMPLETED repository with no indexed chunks returns 400."""
    # Ingest a repository and mock successful clone so status is COMPLETED
    from unittest.mock import patch

    async def mock_clone(url: str, repo_id):
        repo_dir = tmp_path / str(repo_id)
        repo_dir.mkdir(parents=True, exist_ok=True)
        (repo_dir / "code.py").write_text("print(1)\n", encoding="utf-8")
        return repo_dir

    with patch("app.services.repository_ingestion.RepositoryCloner") as MockClonerClass:
        mock_cloner = MockClonerClass.return_value
        mock_cloner.clone = AsyncMock(side_effect=mock_clone)
        mock_cloner.cleanup = AsyncMock()

        create_res = client.post("/repositories", json={"url": "https://github.com/test/completed-unindexed-agent"})
        assert create_res.status_code == 201
        repo_id = create_res.json()["id"]

    # Now status is COMPLETED, but /index has not been called (0 chunks)
    # Using real service with tmp_path storage root
    real_agent_service = AgentService(
        agent_tools=AgentTools(storage_root=tmp_path),
    )
    fastapi_app.dependency_overrides[get_agent_service] = lambda: real_agent_service

    res = client.post(f"/repositories/{repo_id}/agent", json={"question": "Analyze unindexed repo"})
    assert res.status_code == 400
    assert "no indexed code chunks" in res.json()["detail"].lower()


def test_api_agent_validation_errors(client):
    """Empty question returns 422 Unprocessable Entity."""
    repo_id = uuid4()
    res = client.post(f"/repositories/{repo_id}/agent", json={"question": ""})
    assert res.status_code == 422
