"""
Tests for Agent citation integrity, stable source IDs, and rejection of hallucinated sources.
"""

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.agent import AgentStatus
from app.services.agent import AgentService
from app.services.agent_llm import MockAgentLLMService
from app.services.agent_state import SourceRegistry
from app.services.agent_tools import AgentTools


def test_source_registry_deduplicates_and_assigns_stable_ids():
    """SourceRegistry assigns stable IDs (src_1, src_2) and reuses IDs for identical ranges."""
    registry = SourceRegistry()

    id1 = registry.register("src/main.py", 1, 20, "search")
    id2 = registry.register("src/auth.py", 10, 30, "read")
    id3 = registry.register("src/main.py", 1, 20, "read")  # duplicate of id1

    assert id1 == "src_1"
    assert id2 == "src_2"
    assert id3 == "src_1"

    citations = registry.get_citations()
    assert len(citations) == 2
    assert citations[0].source_id == "src_1"
    assert citations[1].source_id == "src_2"


async def _setup_citation_repo(db: AsyncSession, storage_root: Path):
    repo_id = uuid4()
    repo = Repository(
        id=repo_id,
        url="https://github.com/citation-test/repo",
        name="citation-test/repo",
        status=IngestionStatus.COMPLETED,
    )
    db.add(repo)
    await db.flush()

    repo_dir = storage_root / str(repo_id)
    repo_dir.mkdir(parents=True)
    (repo_dir / "valid.py").write_text("x = 1\ny = 2\nz = 3\n", encoding="utf-8")

    cf = CodeFile(repository_id=repo.id, path="valid.py", extension=".py", size_bytes=18)
    db.add(cf)
    await db.flush()

    c = CodeChunk(file_id=cf.id, chunk_index=0, content="code", start_line=1, end_line=3, embedding=[0.1] * 384)
    db.add(c)
    await db.flush()

    return repo


async def test_llm_hallucinated_source_ids_rejected(db_session, tmp_path):
    """If the LLM specifies non-existent source IDs or fabricated paths, they are filtered out."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_citation_repo(db_session, storage_root)

    # LLM reads valid.py (which registers src_1), then tries to cite fake sources:
    scripted_llm = MockAgentLLMService(scripted_responses=[
        {"type": "tool", "tool": "read_file", "arguments": {"path": "valid.py", "start_line": 1, "end_line": 2}},
        {
            "type": "final",
            "answer": "Answer citing fake.py:999-1000",
            # src_1 is valid, others are completely fabricated
            "source_ids": ["src_1", "src_999", "fake.py:999-1000"],
        },
    ])

    tools = AgentTools(storage_root=storage_root)
    agent_service = AgentService(agent_tools=tools, llm_service=scripted_llm)

    response = await agent_service.run(
        repository_id=repo.id,
        question="Check citations",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    assert len(response.sources) == 1
    assert response.sources[0].source_id == "src_1"
    assert response.sources[0].path == "valid.py"
    assert response.sources[0].start_line == 1
    assert response.sources[0].end_line == 2
    assert not any("fake" in s.path for s in response.sources)


async def test_unobserved_files_cannot_become_citations(db_session, tmp_path):
    """Files that were never successfully observed by tools can never appear in sources."""
    storage_root = tmp_path / "storage"
    storage_root.mkdir()
    repo = await _setup_citation_repo(db_session, storage_root)

    # Attempt to read a missing file (fails), then final answer
    scripted_llm = MockAgentLLMService(scripted_responses=[
        {"type": "tool", "tool": "read_file", "arguments": {"path": "nonexistent.py"}},
        {"type": "final", "answer": "Concluded without observing any content."},
    ])

    tools = AgentTools(storage_root=storage_root)
    agent_service = AgentService(agent_tools=tools, llm_service=scripted_llm)

    response = await agent_service.run(
        repository_id=repo.id,
        question="Find nonexistent",
        db=db_session,
    )

    assert response.status == AgentStatus.COMPLETED
    # Because read_file failed, no sources were observed -> sources must be empty
    assert len(response.sources) == 0
