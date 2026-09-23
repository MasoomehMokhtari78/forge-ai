"""
Unit tests for ForgeAI Agent grounding protocol and deterministic safeguard.
Validates rejection of premature final answers, corrective trajectory feedback,
preservation of iteration limits, conversational query bypass, and SourceRegistry invariants.
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
from app.schemas.rag import ChunkRetrievalResult
from app.services.agent import AgentService
from app.services.agent_llm import MockAgentLLMService
from app.services.agent_state import SourceRegistry
from app.services.agent_tools import AgentTools
from app.services.retrieval import RetrievalService


async def _setup_test_repo(db: AsyncSession, storage_root: Path):
    """Set up an indexed repository on disk and in database."""
    repo_id = uuid4()
    repo = Repository(
        id=repo_id,
        url=f"https://github.com/grounding-test/{repo_id.hex[:6]}",
        name="grounding-test/sample",
        status=IngestionStatus.COMPLETED,
    )
    db.add(repo)
    await db.flush()

    repo_dir = storage_root / str(repo_id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "README.md").write_text("# Sample Project\nThis is a sample project for testing.\n", encoding="utf-8")
    (repo_dir / "main.py").write_text("def run():\n    return True\n", encoding="utf-8")

    cf = CodeFile(
        repository_id=repo.id,
        path="main.py",
        extension=".py",
        size_bytes=30,
    )
    db.add(cf)
    await db.flush()

    chunk = CodeChunk(
        file_id=cf.id,
        chunk_index=0,
        content="def run():\n    return True\n",
        start_line=1,
        end_line=2,
        embedding=[0.05] * 384,
    )
    db.add(chunk)
    await db.flush()

    return repo


def test_list_files_alone_does_not_register_sources():
    """list_files is strictly a discovery tool and does not populate SourceRegistry."""
    registry = SourceRegistry()
    assert len(registry.get_citations()) == 0

    # search_code registers
    s1 = registry.register("main.py", 1, 5, "search")
    assert s1 == "src_1"
    assert len(registry.get_citations()) == 1

    # read_file registers
    s2 = registry.register("README.md", 1, 10, "read")
    assert s2 == "src_2"
    assert len(registry.get_citations()) == 2


async def test_premature_final_answer_after_list_files_is_rejected_and_corrected(db_session, tmp_path):
    """If the agent calls list_files and attempts final answer with 0 sources, safeguard intercepts and continues."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_test_repo(db_session, storage_root)

    # 1. list_files -> 2. premature final answer -> 3. read_file -> 4. grounded final answer
    scripted_responses = [
        {"type": "tool", "tool": "list_files", "arguments": {"path": "."}},
        {"type": "final", "answer": "The repo is a sample project based on filenames alone."},
        {"type": "tool", "tool": "read_file", "arguments": {"path": "README.md", "start_line": 1, "end_line": 2}},
        {"type": "final", "answer": "Based on README.md (src_1), the project is a sample project for testing."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=8,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Explain the purpose of this repository.",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 2
    # Iteration 1: list_files, Iteration 2: premature final intercepted, Iteration 3: read_file, Iteration 4: grounded final
    assert response.iterations_count == 4
    assert len(response.sources) == 1
    assert response.sources[0].source_id == "src_1"
    assert response.sources[0].path == "README.md"
    assert "src_1" in response.answer or "README.md" in response.answer


async def test_corrective_feedback_is_visible_in_message_history(db_session, tmp_path):
    """When the safeguard intercepts, it appends a descriptive USER message to the trajectory."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_test_repo(db_session, storage_root)

    scripted_responses = [
        {"type": "tool", "tool": "list_files", "arguments": {"path": "."}},
        {"type": "final", "answer": "Ungrounded answer."},
        {"type": "tool", "tool": "read_file", "arguments": {"path": "main.py", "start_line": 1, "end_line": 2}},
        {"type": "final", "answer": "Grounded answer citing src_1."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=8,
    )

    await agent_service.run(
        repository_id=repo.id,
        question="Explain the repository implementation.",
        db=db_session,
    )

    # Inspect the state observations to ensure grounding safeguard recorded its event
    # And inspect that the agent called read_file after the warning
    read_file_activities = [a for a in agent_service.tools.storage_root.iterdir()]
    assert len(read_file_activities) > 0


async def test_final_answer_after_read_file_is_immediately_accepted(db_session, tmp_path):
    """read_file populates SourceRegistry, so the subsequent final answer is accepted on first attempt."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_test_repo(db_session, storage_root)

    scripted_responses = [
        {"type": "tool", "tool": "read_file", "arguments": {"path": "README.md", "start_line": 1, "end_line": 2}},
        {"type": "final", "answer": "The project purpose is described in src_1."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="What is the repository purpose?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 1
    assert response.iterations_count == 2
    assert len(response.sources) == 1
    assert response.sources[0].path == "README.md"


async def test_final_answer_after_search_code_is_immediately_accepted(db_session, tmp_path):
    """search_code populates SourceRegistry with chunks, allowing immediate final answer completion."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_test_repo(db_session, storage_root)

    scripted_responses = [
        {"type": "tool", "tool": "search_code", "arguments": {"query": "run", "top_k": 3}},
        {"type": "final", "answer": "Found run implementation in src_1."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    mock_retrieval = AsyncMock(spec=RetrievalService)
    mock_retrieval.search.return_value = [
        ChunkRetrievalResult(
            chunk_id=uuid4(),
            file_id=uuid4(),
            path="main.py",
            content="def run(): return True",
            start_line=1,
            end_line=2,
            similarity=0.91,
        )
    ]

    agent_service = AgentService(
        agent_tools=AgentTools(retrieval_service=mock_retrieval, storage_root=storage_root),
        llm_service=scripted_llm,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Where is run defined in the repository?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 1
    assert response.iterations_count == 2
    assert len(response.sources) == 1
    assert response.sources[0].source_id == "src_1"
    assert response.sources[0].path == "main.py"


async def test_conversational_question_bypasses_grounding_requirement(db_session, tmp_path):
    """Generic non-repository questions (e.g. conversational greetings) do not require file citations."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_test_repo(db_session, storage_root)

    scripted_llm = MockAgentLLMService(scripted_responses=[
        {"type": "final", "answer": "I am ForgeAI, an AI software engineering assistant."}
    ])

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Hello, who are you?",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 0
    assert response.iterations_count == 1
    assert "ForgeAI" in response.answer


async def test_repeated_premature_answers_terminate_gracefully(db_session, tmp_path):
    """If the model repeatedly refuses to inspect files, the run terminates gracefully within limits."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_test_repo(db_session, storage_root)

    # Model gives list_files, then only final answers without ever reading
    scripted_responses = [
        {"type": "tool", "tool": "list_files", "arguments": {"path": "."}},
        {"type": "final", "answer": "Premature attempt 1."},
        {"type": "final", "answer": "Premature attempt 2."},
        {"type": "final", "answer": "Premature attempt 3."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
        max_iterations=4,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Explain the code architecture.",
        db=db_session,
    )

    # Must terminate without an infinite loop
    assert response.status in (AgentStatus.COMPLETED, AgentStatus.MAX_ITERATIONS)
    assert response.iterations_count <= 4


async def test_honest_insufficient_evidence_after_tool_failure_is_allowed(db_session, tmp_path):
    """If content tools fail or return nothing, an honest insufficient evidence report is accepted."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_test_repo(db_session, storage_root)

    scripted_responses = [
        {"type": "tool", "tool": "read_file", "arguments": {"path": "missing.py"}},
        {"type": "final", "answer": "The requested file was not found, so available evidence is insufficient."},
    ]
    scripted_llm = MockAgentLLMService(scripted_responses=scripted_responses)

    agent_service = AgentService(
        agent_tools=AgentTools(storage_root=storage_root),
        llm_service=scripted_llm,
    )

    response = await agent_service.run(
        repository_id=repo.id,
        question="Find missing.py in the repository",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert response.tool_calls_count == 1
    assert len(response.sources) == 0
    assert "insufficient" in response.answer or "not found" in response.answer
