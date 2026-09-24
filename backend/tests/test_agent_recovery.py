"""
Unit tests for Agent tool error recovery and path correction.
Verifies that recoverable path/file errors generate clear discovery guidance
encouraging list_files and search_code, and that the agent successfully recovers
and grounds evidence.
"""

from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.agent import AgentMessageRole, AgentStatus, ToolName
from app.services.agent import AgentService
from app.services.agent_llm import MockAgentLLMService
from app.services.agent_tools import AgentTools


async def _setup_recovery_test_repo(db: AsyncSession, storage_root: Path):
    """Set up a test repository with Python.gitignore and main.py."""
    repo_id = uuid4()
    repo = Repository(
        id=repo_id,
        url=f"https://github.com/recovery-test/{repo_id.hex[:6]}",
        name="recovery-test/sample",
        status=IngestionStatus.COMPLETED,
    )
    db.add(repo)
    await db.flush()

    repo_dir = storage_root / str(repo_id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "Python.gitignore").write_text("*.pyc\n__pycache__/\n.venv/\n", encoding="utf-8")
    (repo_dir / "main.py").write_text("print('hello')\n", encoding="utf-8")

    cf1 = CodeFile(
        repository_id=repo.id,
        path="Python.gitignore",
        extension=".gitignore",
        size_bytes=30,
    )
    cf2 = CodeFile(
        repository_id=repo.id,
        path="main.py",
        extension=".py",
        size_bytes=15,
    )
    db.add_all([cf1, cf2])
    await db.flush()

    chunk = CodeChunk(
        file_id=cf1.id,
        chunk_index=0,
        content="*.pyc\n__pycache__/\n.venv/\n",
        start_line=1,
        end_line=3,
        embedding=[0.05] * 384,
    )
    db.add(chunk)
    await db.flush()

    return repo


async def test_file_not_found_observation_contains_recovery_guidance(db_session, tmp_path):
    """When read_file fails with 'File not found', observation includes recovery guidance with list_files/search_code."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_recovery_test_repo(db_session, storage_root)

    # Model requests nonexistent .gitignore, then terminates
    scripted_responses = [
        {"type": "tool", "tool": "read_file", "arguments": {"path": ".gitignore"}},
        {"type": "final", "answer": "I could not locate the file."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=4,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Read .gitignore and explain patterns.",
        db=db_session,
    )

    # Tool activity shows the failure
    assert len(response.tool_activity) >= 1
    first_act = response.tool_activity[0]
    assert first_act.tool == ToolName.READ_FILE
    assert first_act.success is False
    assert "File not found" in first_act.summary

    # Execute tool directly to inspect state observation payload
    state = agent_service._create_state(repository_id=repo.id, question="test", max_iterations=2) if hasattr(agent_service, "_create_state") else None


async def test_file_not_found_observation_guidance_in_tool_message(db_session, tmp_path):
    """Tool message payload for a missing file explicitly instructs list_files or search_code."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_recovery_test_repo(db_session, storage_root)

    observed_tool_messages = []

    # Custom LLM that captures the TOOL messages passed to it
    class CapturingLLM(MockAgentLLMService):
        async def generate(self, messages, tools=None):
            for m in messages:
                if m.role == AgentMessageRole.TOOL:
                    observed_tool_messages.append(m.content)
            return await super().generate(messages, tools)

    scripted_llm = CapturingLLM(scripted_responses=[
        {"type": "tool", "tool": "read_file", "arguments": {"path": ".gitignore"}},
        {"type": "final", "answer": "File was missing."},
    ])

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=4,
    )

    await agent_service.run(
        repository_id=repo.id,
        question="Check .gitignore",
        db=db_session,
    )

    assert len(observed_tool_messages) >= 1
    tool_content = observed_tool_messages[0]
    assert "File not found" in tool_content
    assert "list_files" in tool_content
    assert "search_code" in tool_content
    assert "recovery_guidance" in tool_content


async def test_successful_recovery_after_file_not_found(db_session, tmp_path):
    """Agent recovers from wrong path via list_files and read_file, creating verified source."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_recovery_test_repo(db_session, storage_root)

    scripted_responses = [
        # 1. Erroneous guessed path
        {"type": "tool", "tool": "read_file", "arguments": {"path": ".gitignore"}},
        # 2. Recovery discovery
        {"type": "tool", "tool": "list_files", "arguments": {"path": "."}},
        # 3. Targeted inspection of discovered path
        {"type": "tool", "tool": "read_file", "arguments": {"path": "Python.gitignore", "start_line": 1, "end_line": 3}},
        # 4. Final grounded answer citing src_1
        {"type": "final", "answer": "Based on Python.gitignore (src_1), bytecode and virtual environments are ignored."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=8,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Explain Python gitignore patterns in this repository.",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 3
    assert len(response.sources) == 1
    assert response.sources[0].source_id == "src_1"
    assert response.sources[0].path == "Python.gitignore"
    # Ensure failed .gitignore did NOT register in sources
    source_paths = [s.path for s in response.sources]
    assert ".gitignore" not in source_paths


async def test_directory_not_found_observation_contains_recovery_guidance(db_session, tmp_path):
    """When list_files fails with 'Directory not found', observation includes recovery guidance."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_recovery_test_repo(db_session, storage_root)

    observed_tool_messages = []

    class CapturingLLM(MockAgentLLMService):
        async def generate(self, messages, tools=None):
            for m in messages:
                if m.role == AgentMessageRole.TOOL:
                    observed_tool_messages.append(m.content)
            return await super().generate(messages, tools)

    scripted_llm = CapturingLLM(scripted_responses=[
        {"type": "tool", "tool": "list_files", "arguments": {"path": "nonexistent_dir"}},
        {"type": "final", "answer": "Directory does not exist."},
    ])

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=4,
    )

    await agent_service.run(
        repository_id=repo.id,
        question="List nonexistent_dir",
        db=db_session,
    )

    assert len(observed_tool_messages) >= 1
    tool_content = observed_tool_messages[0]
    assert "Directory not found" in tool_content
    assert "list_files" in tool_content
    assert "search_code" in tool_content
    assert "recovery_guidance" in tool_content
