"""
Tests for RAGService orchestration, citation integrity, and budget-scoped attribution.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.schemas.rag import ChunkRetrievalResult, Citation
from app.services.context_builder import ContextBuilder
from app.services.llm import LLMService, MockLLMService
from app.services.prompt_builder import PromptBuilder
from app.services.rag import RAGService
from app.services.retrieval import RetrievalService


def _create_chunk(path: str, start_line: int, end_line: int, content: str = "code") -> ChunkRetrievalResult:
    return ChunkRetrievalResult(
        chunk_id=uuid4(),
        file_id=uuid4(),
        path=path,
        content=content,
        start_line=start_line,
        end_line=end_line,
        similarity=0.9,
    )


async def test_rag_service_end_to_end():
    """RAGService coordinates retrieval, budgeting, prompt construction, and returns answer + citations."""
    mock_retrieval = AsyncMock(spec=RetrievalService)
    repo_id = uuid4()
    chunks = [
        _create_chunk("src/auth.py", 1, 20, "def auth(): pass"),
        _create_chunk("src/models.py", 10, 30, "class User: pass"),
    ]
    mock_retrieval.search.return_value = chunks

    rag_service = RAGService(
        retrieval_service=mock_retrieval,
        context_builder=ContextBuilder(),
        prompt_builder=PromptBuilder(),
        llm_service=MockLLMService(),
    )

    db_mock = AsyncMock()
    response = await rag_service.answer_question(
        repository_id=repo_id,
        question="How does auth work?",
        db=db_mock,
    )

    assert "[MOCK LLM RESPONSE]" in response.answer
    assert len(response.sources) == 2
    assert response.sources[0] == Citation(path="src/auth.py", start_line=1, end_line=20)
    assert response.sources[1] == Citation(path="src/models.py", start_line=10, end_line=30)


async def test_llm_hallucinated_citations_cannot_alter_sources():
    """Security Invariant: Citations in ChatResponse are derived ONLY from chunk metadata.

    Even if the LLM outputs fabricated file paths and line numbers in its answer text,
    they must NEVER be included in ChatResponse.sources.
    """
    class MaliciousHallucinatingLLM(LLMService):
        async def generate(self, prompt: str) -> str:
            return (
                "Here is the answer. See source at src/completely_fake_file.py:999 "
                "and also evil/hack.py:1-500."
            )

    mock_retrieval = AsyncMock(spec=RetrievalService)
    repo_id = uuid4()
    actual_chunk = _create_chunk("src/real_auth.py", 5, 15, "real code")
    mock_retrieval.search.return_value = [actual_chunk]

    rag_service = RAGService(
        retrieval_service=mock_retrieval,
        context_builder=ContextBuilder(),
        prompt_builder=PromptBuilder(),
        llm_service=MaliciousHallucinatingLLM(),
    )

    response = await rag_service.answer_question(
        repository_id=repo_id,
        question="Any question",
        db=AsyncMock(),
    )

    # The answer text contains the fake path:
    assert "src/completely_fake_file.py" in response.answer

    # But sources must contain ONLY the actual chunk metadata!
    assert len(response.sources) == 1
    assert response.sources[0] == Citation(path="src/real_auth.py", start_line=5, end_line=15)
    assert not any("fake" in s.path or "evil" in s.path for s in response.sources)


async def test_budget_excluded_chunks_are_not_cited():
    """A chunk retrieved from the database but excluded by ContextBuilder's character budget

    must NOT appear in ChatResponse.sources.
    """
    mock_retrieval = AsyncMock(spec=RetrievalService)
    repo_id = uuid4()
    chunk1 = _create_chunk("src/included.py", 1, 10, "short code 1")
    chunk2 = _create_chunk("src/excluded.py", 1, 10, "short code 2")
    mock_retrieval.search.return_value = [chunk1, chunk2]

    # ContextBuilder with tight budget that only fits chunk1
    builder = ContextBuilder()
    rag_service = RAGService(
        retrieval_service=mock_retrieval,
        context_builder=builder,
        prompt_builder=PromptBuilder(),
        llm_service=MockLLMService(),
    )

    # Set max_context_chars so only chunk1 fits
    len_chunk1 = len(builder._format_chunk(1, chunk1))
    response = await rag_service.answer_question(
        repository_id=repo_id,
        question="Any question",
        db=AsyncMock(),
        max_context_chars=len_chunk1 + 5,
    )

    assert len(response.sources) == 1
    assert response.sources[0].path == "src/included.py"


async def test_empty_retrieval_returns_empty_sources():
    """When no chunks are retrieved, RAGService returns a graceful response with empty sources."""
    mock_retrieval = AsyncMock(spec=RetrievalService)
    mock_retrieval.search.return_value = []

    rag_service = RAGService(
        retrieval_service=mock_retrieval,
        context_builder=ContextBuilder(),
        prompt_builder=PromptBuilder(),
        llm_service=MockLLMService(),
    )

    response = await rag_service.answer_question(
        repository_id=uuid4(),
        question="Where is database configured?",
        db=AsyncMock(),
    )

    assert "[MOCK LLM RESPONSE]" in response.answer
    assert "No relevant repository context was found" in response.answer
    assert response.sources == []
