"""
Tests for source code chunking logic (Phase 3).
"""

import pytest

from app.services.chunking import ChunkData, chunk_source_code


def test_empty_file_returns_no_chunks():
    """Empty content and whitespace-only files produce no chunks."""
    assert chunk_source_code("") == []
    assert chunk_source_code("   \n\n\t  ") == []


def test_small_file_produces_one_chunk():
    """A file with fewer lines than chunk_size produces exactly one chunk."""
    content = "line 1\nline 2\nline 3\nline 4\nline 5"
    chunks = chunk_source_code(content, chunk_size=10, chunk_overlap=2)

    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content == content
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 5


def test_exact_fit_produces_one_chunk():
    """A file whose line count equals chunk_size produces exactly one chunk."""
    lines = [f"line {i}" for i in range(1, 11)]
    content = "\n".join(lines)
    chunks = chunk_source_code(content, chunk_size=10, chunk_overlap=3)

    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 10


def test_larger_file_produces_multiple_chunks():
    """A file exceeding chunk_size produces multiple ordered chunks."""
    lines = [f"line {i}" for i in range(1, 26)]  # 25 lines
    content = "\n".join(lines)
    chunks = chunk_source_code(content, chunk_size=10, chunk_overlap=2)

    # Step is 10 - 2 = 8
    # Chunk 0: lines 1-10
    # Chunk 1: lines 9-18
    # Chunk 2: lines 17-25
    assert len(chunks) == 3
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_chunk_overlap_works_correctly():
    """Consecutive chunks overlap by the specified number of lines."""
    lines = [f"line {i}" for i in range(1, 21)]  # 20 lines
    content = "\n".join(lines)
    chunk_size = 8
    overlap = 3
    chunks = chunk_source_code(content, chunk_size=chunk_size, chunk_overlap=overlap)

    # Step is 8 - 3 = 5
    # Chunk 0: start 1, end 8
    # Chunk 1: start 6, end 13 (overlaps lines 6, 7, 8 with Chunk 0)
    # Chunk 2: start 11, end 18 (overlaps lines 11, 12, 13 with Chunk 1)
    # Chunk 3: start 16, end 20 (overlaps lines 16, 17, 18 with Chunk 2)
    assert len(chunks) == 4

    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 8

    assert chunks[1].start_line == 6
    assert chunks[1].end_line == 13

    assert chunks[2].start_line == 11
    assert chunks[2].end_line == 18

    assert chunks[3].start_line == 16
    assert chunks[3].end_line == 20

    # Verify overlap content matches
    chunk0_lines = chunks[0].content.splitlines()
    chunk1_lines = chunks[1].content.splitlines()
    assert chunk0_lines[-overlap:] == chunk1_lines[:overlap]


def test_chunking_is_deterministic():
    """The same input content always produces identical chunks across multiple calls."""
    content = "\n".join(f"def func_{i}():\n    return {i}" for i in range(50))

    run_1 = chunk_source_code(content, chunk_size=15, chunk_overlap=5)
    run_2 = chunk_source_code(content, chunk_size=15, chunk_overlap=5)

    assert len(run_1) == len(run_2)
    for c1, c2 in zip(run_1, run_2):
        assert c1.chunk_index == c2.chunk_index
        assert c1.content == c2.content
        assert c1.start_line == c2.start_line
        assert c1.end_line == c2.end_line


def test_invalid_parameters_raise_value_error():
    """Invalid chunk_size or overlap parameters raise ValueError."""
    content = "hello world"
    with pytest.raises(ValueError):
        chunk_source_code(content, chunk_size=0)

    with pytest.raises(ValueError):
        chunk_source_code(content, chunk_size=10, chunk_overlap=-1)

    with pytest.raises(ValueError):
        chunk_source_code(content, chunk_size=10, chunk_overlap=10)

    with pytest.raises(ValueError):
        chunk_source_code(content, chunk_size=10, chunk_overlap=15)
