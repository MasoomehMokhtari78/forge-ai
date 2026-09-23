"""
Tests for AgentService stopping conditions: max iterations, max tool calls, and loop termination.
"""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.agent import AgentStatus
from app.services.agent import AgentService
from app.services.agent_llm import MockAgentLLMService
from app.services.agent_prompt_builder import AgentPromptBuilder
from app.services.agent_tools import AgentTools


async def _setup_dummy_repo(db: AsyncSession, storage_root: Path):
    repo_id = uuid4()
    repo = Repository(
        id=repo_id,
        url=f"https://github.com/stopping-test/{repo_id.hex[:6]}",
        name="stopping-test/sample",
        status=IngestionStatus.COMPLETED,
    )
    db.add(repo)
    await db.flush()

    repo_dir = storage_root / str(repo_id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "file.py").write_text("print('test')\n", encoding="utf-8")

    cf = CodeFile(
        repository_id=repo.id,
        path="file.py",
        extension=".py",
        size_bytes=15,
    )
    db.add(cf)
    await db.flush()

    chunk = CodeChunk(
        file_id=cf.id,
        chunk_index=0,
        content="print('test')\n",
        start_line=1,
        end_line=1,
        embedding=[0.05] * 384,
    )
    db.add(chunk)
    await db.flush()

    return repo


async def test_agent_stops_at_max_iterations(db_session, tmp_path):
    """Agent terminates with MAX_ITERATIONS status when iteration budget is exhausted."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_dummy_repo(db_session, storage_root)

    # LLM requests read_file endlessly
    infinite_tool_responses = [
        {"type": "tool", "tool": "read_file", "arguments": {"path": "file.py"}}
        for _ in range(20)
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=infinite_tool_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=3,
        max_tool_calls=10,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Keep running",
        db=db_session,
    )

    assert response.status == AgentStatus.MAX_ITERATIONS
    assert response.iterations_count == 3
    assert "[AGENT MAX_ITERATIONS]" in response.answer


async def test_agent_stops_at_max_tool_calls(db_session, tmp_path):
    """Agent terminates with MAX_TOOL_CALLS status when tool call limit is reached."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_dummy_repo(db_session, storage_root)

    infinite_tool_responses = [
        {"type": "tool", "tool": "read_file", "arguments": {"path": "file.py"}}
        for _ in range(20)
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=infinite_tool_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=10,
        max_tool_calls=2,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Keep calling tools",
        db=db_session,
    )

    assert response.status == AgentStatus.MAX_TOOL_CALLS
    assert response.tool_calls_count == 2
    assert "[AGENT MAX_TOOL_CALLS]" in response.answer


def test_agent_prompt_builder_truncates_oversized_history():
    """Observation history is cleanly truncated when it exceeds agent_max_context_chars."""
    builder = AgentPromptBuilder(max_context_chars=300)
    long_observations = [
        {
            "iteration": i,
            "tool": "search_code",
            "arguments": {"query": f"search_{i}"},
            "success": True,
            "data": {"snippet": "x" * 100},
        }
        for i in range(1, 10)
    ]

    prompt = builder.build_prompt(
        question="Summary question",
        iteration=10,
        max_iterations=10,
        observations=long_observations,
    )

    assert "[...earlier observations truncated...]" in prompt
    assert "User Question: Summary question" in prompt
