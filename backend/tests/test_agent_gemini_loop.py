"""
End-to-end unit tests of the AgentService loop driven by GeminiAgentLLMService
(with mocked google-genai client responses).
Validates multi-step trajectories, sequential reads, error recovery,
citation verification against hallucinated IDs, and boundary limits.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.agent import AgentStatus, ToolName
from app.schemas.rag import ChunkRetrievalResult
from app.services.agent import AgentService
from app.services.agent_tools import AgentTools
from app.services.gemini_agent_llm import GeminiAgentLLMService
from app.services.retrieval import RetrievalService


async def _setup_indexed_repo(db: AsyncSession, storage_root: Path):
    repo_id = uuid4()
    repo = Repository(
        id=repo_id,
        url=f"https://github.com/gemini-loop-test/{repo_id.hex[:6]}",
        name="gemini-loop-test/sample",
        status=IngestionStatus.COMPLETED,
    )
    db.add(repo)
    await db.flush()

    repo_dir = storage_root / str(repo_id)
    repo_dir.mkdir(parents=True)
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (src_dir / "auth.py").write_text("def auth():\n    return True\n", encoding="utf-8")
    (src_dir / "db.py").write_text("def connect():\n    return 'db'\n", encoding="utf-8")

    for path in ["src/main.py", "src/auth.py", "src/db.py"]:
        cf = CodeFile(
            repository_id=repo.id,
            path=path,
            extension=".py",
            size_bytes=30,
        )
        db.add(cf)
        await db.flush()

        chunk = CodeChunk(
            file_id=cf.id,
            chunk_index=0,
            content=f"# Content of {path}\n",
            start_line=1,
            end_line=1,
            embedding=[0.05] * 384,
        )
        db.add(chunk)
        await db.flush()

    return repo


def _make_gemini_resp(tool_name: str | None = None, args: dict | None = None, text: str | None = None):
    function_calls = None
    if tool_name:
        function_calls = [SimpleNamespace(name=tool_name, args=args or {})]
    candidates = []
    if text:
        candidates = [
            SimpleNamespace(
                content=SimpleNamespace(
                    parts=[SimpleNamespace(function_call=None, text=text)]
                )
            )
        ]
    return SimpleNamespace(
        function_calls=function_calls,
        candidates=candidates,
        text=text,
    )


async def test_agent_gemini_loop_search_then_read_then_final(db_session, tmp_path):
    """Test standard Gemini trajectory: search -> read -> final answer."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_indexed_repo(db_session, storage_root)

    # Sequence of 3 Gemini responses
    resp_1 = _make_gemini_resp(tool_name="search_code", args={"query": "auth", "top_k": 3})
    resp_2 = _make_gemini_resp(tool_name="read_file", args={"path": "src/auth.py", "start_line": 1, "end_line": 2})
    resp_3 = _make_gemini_resp(text="Authentication is implemented in src/auth.py. See src_1.")

    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio
    mock_aio.models.generate_content = AsyncMock(side_effect=[resp_1, resp_2, resp_3])

    mock_retrieval = AsyncMock(spec=RetrievalService)
    mock_retrieval.search.return_value = [
        ChunkRetrievalResult(
            chunk_id=uuid4(),
            file_id=uuid4(),
            path="src/auth.py",
            content="def auth(): return True",
            start_line=1,
            end_line=1,
            similarity=0.95,
        )
    ]

    gemini_llm = GeminiAgentLLMService(api_key="test-key", client=mock_client)
    agent = AgentService(
        agent_tools=AgentTools(retrieval_service=mock_retrieval, storage_root=storage_root),
        llm_service=gemini_llm,
    )

    response = await agent.run(
        repository_id=repo.id,
        question="How does authentication work?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.iterations_count == 3
    assert response.tool_calls_count == 2
    assert len(response.tool_activity) == 2
    assert response.tool_activity[0].tool == ToolName.SEARCH_CODE
    assert response.tool_activity[1].tool == ToolName.READ_FILE
    assert "src/auth.py" in response.answer

    # Verify citations
    assert len(response.sources) >= 1
    assert any(s.path == "src/auth.py" for s in response.sources)


async def test_agent_gemini_loop_multiple_sequential_reads(db_session, tmp_path):
    """Test search -> read file 1 -> read file 2 -> final answer trajectory."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_indexed_repo(db_session, storage_root)

    resp_1 = _make_gemini_resp(tool_name="search_code", args={"query": "setup", "top_k": 2})
    resp_2 = _make_gemini_resp(tool_name="read_file", args={"path": "src/main.py", "start_line": 1, "end_line": 2})
    resp_3 = _make_gemini_resp(tool_name="read_file", args={"path": "src/db.py", "start_line": 1, "end_line": 2})
    resp_4 = _make_gemini_resp(text="The main entry point loads DB from src/db.py.")

    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio
    mock_aio.models.generate_content = AsyncMock(side_effect=[resp_1, resp_2, resp_3, resp_4])

    gemini_llm = GeminiAgentLLMService(api_key="test-key", client=mock_client)
    agent = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=gemini_llm,
    )

    response = await agent.run(
        repository_id=repo.id,
        question="How does startup and DB initialization work?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.iterations_count == 4
    assert response.tool_calls_count == 3
    assert response.tool_activity[1].tool == ToolName.READ_FILE
    assert response.tool_activity[2].tool == ToolName.READ_FILE


async def test_agent_gemini_hallucinated_citation_id_rejected(db_session, tmp_path):
    """If Gemini cites an invented source ID like 'src_fake' or 'src_999', it is not accepted."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_indexed_repo(db_session, storage_root)

    resp_1 = _make_gemini_resp(tool_name="read_file", args={"path": "src/main.py", "start_line": 1, "end_line": 2})
    # Gemini claims answer is based on src_fake and src_999
    resp_2 = _make_gemini_resp(text="According to [src_fake] and [src_999], the system works like this.")

    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio
    mock_aio.models.generate_content = AsyncMock(side_effect=[resp_1, resp_2])

    gemini_llm = GeminiAgentLLMService(api_key="test-key", client=mock_client)
    agent = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=gemini_llm,
    )

    response = await agent.run(
        repository_id=repo.id,
        question="How does main work?",
        db=db_session,
    )

    # Verification: src_fake and src_999 are NOT present in sources
    for src in response.sources:
        assert src.source_id != "src_fake"
        assert src.source_id != "src_999"
        # Must be valid registered source ID (e.g. src_1 from read_file)
        assert src.source_id == "src_1"
        assert src.path == "src/main.py"


async def test_agent_gemini_recovers_from_tool_error(db_session, tmp_path):
    """If Gemini requests a non-existent file, the error observation is sent back and Gemini recovers."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_indexed_repo(db_session, storage_root)

    resp_1 = _make_gemini_resp(tool_name="read_file", args={"path": "missing_file.py"})
    resp_2 = _make_gemini_resp(tool_name="read_file", args={"path": "src/main.py", "start_line": 1, "end_line": 2})
    resp_3 = _make_gemini_resp(text="File was actually in src/main.py.")

    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio
    mock_aio.models.generate_content = AsyncMock(side_effect=[resp_1, resp_2, resp_3])

    gemini_llm = GeminiAgentLLMService(api_key="test-key", client=mock_client)
    agent = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=gemini_llm,
    )

    response = await agent.run(
        repository_id=repo.id,
        question="Find file",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 2
    assert response.tool_activity[0].success is False
    assert response.tool_activity[1].success is True
    assert "src/main.py" in response.answer


async def test_agent_gemini_stops_at_max_iterations(db_session, tmp_path):
    """If Gemini keeps requesting tools beyond max_iterations, the loop stops cleanly."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_indexed_repo(db_session, storage_root)

    infinite_resp = _make_gemini_resp(tool_name="read_file", args={"path": "src/main.py", "start_line": 1, "end_line": 2})

    mock_client = MagicMock()
    mock_aio = MagicMock()
    mock_client.aio = mock_aio
    mock_aio.models.generate_content = AsyncMock(return_value=infinite_resp)

    gemini_llm = GeminiAgentLLMService(api_key="test-key", client=mock_client)
    agent = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=gemini_llm,
        max_iterations=3,
        max_tool_calls=10,
    )

    response = await agent.run(
        repository_id=repo.id,
        question="Keep running",
        db=db_session,
    )

    assert response.status == AgentStatus.MAX_ITERATIONS
    assert response.iterations_count == 3
    assert "[AGENT MAX_ITERATIONS]" in response.answer
