"""
Unit tests for ContextBuilder: structured formatting, complete-string budgeting, and inclusion tracking.
"""

from uuid import uuid4

from app.schemas.rag import ChunkRetrievalResult
from app.services.context_builder import ContextBuilder


def _make_chunk(
    path: str = "src/main.py",
    content: str = "print('hello world')",
    start_line: int = 1,
    end_line: int = 5,
    similarity: float = 0.85,
) -> ChunkRetrievalResult:
    return ChunkRetrievalResult(
        chunk_id=uuid4(),
        file_id=uuid4(),
        path=path,
        content=content,
        start_line=start_line,
        end_line=end_line,
        similarity=similarity,
    )


def test_empty_chunks_returns_default_placeholder():
    """Empty list of chunks returns placeholder message and empty included_chunks."""
    builder = ContextBuilder(default_max_chars=4000)
    result = builder.build(chunks=[])

    assert result.context_text == "(No relevant code chunks found)"
    assert result.included_chunks == []


def test_chunk_formatting_structure():
    """Retrieved chunk is formatted with proper headers, file paths, line numbers, and content."""
    builder = ContextBuilder(default_max_chars=4000)
    chunk = _make_chunk(path="app/auth.py", content="def login():\n    return True", start_line=10, end_line=12)

    result = builder.build(chunks=[chunk])

    assert "[Source 1]" in result.context_text
    assert "File: app/auth.py" in result.context_text
    assert "Lines: 10-12" in result.context_text
    assert "def login():\n    return True" in result.context_text
    assert len(result.included_chunks) == 1
    assert result.included_chunks[0] == chunk


def test_complete_string_budgeting_stops_packing():
    """Budget applies to full formatted text (headers + content + separators).

    Chunks that exceed remaining budget are excluded from text AND included_chunks.
    """
    builder = ContextBuilder(default_max_chars=4000)
    chunk1 = _make_chunk(path="a.py", content="short content 1")
    chunk2 = _make_chunk(path="b.py", content="short content 2")
    chunk3 = _make_chunk(path="c.py", content="short content 3")

    # Measure exact formatted length of 1 chunk
    res1 = builder.build(chunks=[chunk1], max_chars=1000)
    len_chunk1 = len(res1.context_text)

    # Set budget that comfortably fits chunk 1, but cannot fit chunk 2 with separator
    strict_budget = len_chunk1 + 10
    result = builder.build(chunks=[chunk1, chunk2, chunk3], max_chars=strict_budget)

    assert len(result.context_text) <= strict_budget
    assert "[Source 1]" in result.context_text
    assert "[Source 2]" not in result.context_text
    assert len(result.included_chunks) == 1
    assert result.included_chunks[0].path == "a.py"


def test_oversized_first_chunk_is_deterministically_truncated():
    """If the first chunk's full formatted block exceeds the entire budget,

    it is deterministically truncated with an explicit marker to respect max_chars.
    """
    builder = ContextBuilder(default_max_chars=4000)
    huge_content = "def long_function():\n" + ("    x = 1\n" * 100)
    oversized_chunk = _make_chunk(path="huge.py", content=huge_content, start_line=1, end_line=101)

    budget = 150
    result = builder.build(chunks=[oversized_chunk], max_chars=budget)

    assert len(result.context_text) <= budget
    assert "[...truncated to context budget...]" in result.context_text
    assert len(result.included_chunks) == 1
    assert result.included_chunks[0].path == "huge.py"


def test_budget_too_small_for_any_content_returns_placeholder():
    """When budget is smaller than header overhead, returns placeholder with no included chunks."""
    builder = ContextBuilder(default_max_chars=4000)
    chunk = _make_chunk(path="test.py", content="hello")

    result = builder.build(chunks=[chunk], max_chars=10)

    assert result.context_text == "(No relevant code chunks found)"
    assert result.included_chunks == []
