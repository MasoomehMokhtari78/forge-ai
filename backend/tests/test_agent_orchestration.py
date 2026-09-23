"""
Tests for AgentService orchestration: multi-step investigation, tool sequences, and error recovery.
"""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.agent import AgentStatus, ToolName
from app.schemas.rag import ChunkRetrievalResult
from app.services.agent import AgentService
from app.services.agent_llm import MockAgentLLMService
from app.services.agent_tools import AgentTools
from app.services.retrieval import RetrievalService


@pytest.fixture
def mock_repo_env(tmp_path: Path):
    """Set up database entities and local files for an indexed repository."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    return storage_root


async def _setup_indexed_repo(db: AsyncSession, storage_root: Path):
    repo_id = uuid4()
    repo = Repository(
        id=repo_id,
        url=f"https://github.com/agent-test/{repo_id.hex[:6]}",
        name="agent-test/sample",
        status=IngestionStatus.COMPLETED,
    )
    db.add(repo)
    await db.flush()

    # Local files on disk
    repo_dir = storage_root / str(repo_id)
    repo_dir.mkdir(parents=True)
    src_dir = repo_dir / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("def main():\n    return 'ok'\n", encoding="utf-8")
    (src_dir / "auth.py").write_text("def authenticate(token):\n    return True\n", encoding="utf-8")

    # DB CodeFile and CodeChunk
    cf = CodeFile(
        repository_id=repo.id,
        path="src/auth.py",
        extension=".py",
        size_bytes=40,
    )
    db.add(cf)
    await db.flush()

    chunk = CodeChunk(
        file_id=cf.id,
        chunk_index=0,
        content="def authenticate(token):\n    return True\n",
        start_line=1,
        end_line=2,
        embedding=[0.1] * 384,
    )
    db.add(chunk)
    await db.flush()

    return repo


async def test_agent_immediate_final_answer(db_session, mock_repo_env):
    """Agent can conclude immediately with a final answer without invoking any tools."""
    repo = await _setup_indexed_repo(db_session, mock_repo_env)

    scripted_llm = MockAgentLLMService(scripted_responses=[
        {"type": "final", "answer": "The answer is straightforward without tools."}
    ])

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=mock_repo_env),
        llm_service=scripted_llm,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="What is the answer?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert "straightforward" in response.answer
    assert response.tool_calls_count == 0
    assert response.iterations_count == 1
    assert len(response.tool_activity) == 0


async def test_agent_single_tool_call_then_final(db_session, mock_repo_env):
    """Agent executes search_code then completes with final answer."""
    repo = await _setup_indexed_repo(db_session, mock_repo_env)

    scripted_llm = MockAgentLLMService(scripted_responses=[
        {"type": "tool", "tool": "search_code", "arguments": {"query": "auth", "top_k": 3}},
        {"type": "final", "answer": "Found auth code in src/auth.py.", "source_ids": ["src_1"]},
    ])

    # Mock retrieval to return chunk
    mock_retrieval = AsyncMock(spec=RetrievalService)
    mock_retrieval.search.return_value = [
        ChunkRetrievalResult(
            chunk_id=uuid4(),
            file_id=uuid4(),
            path="src/auth.py",
            content="def authenticate(token): pass",
            start_line=1,
            end_line=2,
            similarity=0.88,
        )
    ]

    tools = AgentTools(retrieval_service=mock_retrieval, storage_root=mock_repo_env)
    agent_service = AgentService(agent_tools=tools, llm_service=scripted_llm)

    response = await agent_service.run(
        repository_id=repo.id,
        question="How does auth work?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 1
    assert len(response.tool_activity) == 1
    assert response.tool_activity[0].tool == ToolName.SEARCH_CODE
    assert response.tool_activity[0].success is True
    assert len(response.sources) == 1
    assert response.sources[0].source_id == "src_1"
    assert response.sources[0].path == "src/auth.py"


async def test_agent_multi_step_investigation(db_session, mock_repo_env):
    """Agent executes search -> read_file -> final answer sequence."""
    repo = await _setup_indexed_repo(db_session, mock_repo_env)

    scripted_llm = MockAgentLLMService(scripted_responses=[
        {"type": "tool", "tool": "search_code", "arguments": {"query": "token", "top_k": 3}},
        {"type": "tool", "tool": "read_file", "arguments": {"path": "src/auth.py", "start_line": 1, "end_line": 2}},
        {"type": "final", "answer": "Detailed verification complete.", "source_ids": ["src_1", "src_2"]},
    ])

    mock_retrieval = AsyncMock(spec=RetrievalService)
    mock_retrieval.search.return_value = [
        ChunkRetrievalResult(
            chunk_id=uuid4(),
            file_id=uuid4(),
            path="src/auth.py",
            content="def authenticate(token): pass",
            start_line=1,
            end_line=2,
            similarity=0.92,
        )
    ]

    tools = AgentTools(retrieval_service=mock_retrieval, storage_root=mock_repo_env)
    agent_service = AgentService(agent_tools=tools, llm_service=scripted_llm)

    response = await agent_service.run(
        repository_id=repo.id,
        question="Verify auth implementation",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 2
    assert len(response.tool_activity) == 2
    assert response.tool_activity[0].tool == ToolName.SEARCH_CODE
    assert response.tool_activity[1].tool == ToolName.READ_FILE
    assert len(response.sources) >= 1


async def test_agent_recovers_after_tool_failure(db_session, mock_repo_env):
    """If a tool call fails (e.g. read_file on non-existent path), the agent records observation and recovers."""
    repo = await _setup_indexed_repo(db_session, mock_repo_env)

    scripted_llm = MockAgentLLMService(scripted_responses=[
        # Attempt to read non-existent file
        {"type": "tool", "tool": "read_file", "arguments": {"path": "src/nonexistent.py"}},
        # Agent recovers and reads valid file
        {"type": "tool", "tool": "read_file", "arguments": {"path": "src/main.py", "start_line": 1, "end_line": 2}},
        {"type": "final", "answer": "Recovered and found main.py."},
    ])

    tools = AgentTools(storage_root=mock_repo_env)
    agent_service = AgentService(agent_tools=tools, llm_service=scripted_llm)

    response = await agent_service.run(
        repository_id=repo.id,
        question="Find entry point",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 2
    assert len(response.tool_activity) == 2
    # First activity should record failure
    assert response.tool_activity[0].success is False
    assert "File not found" in response.tool_activity[0].summary
    # Second activity should record success
    assert response.tool_activity[1].success is True
    assert "Recovered" in response.answer
