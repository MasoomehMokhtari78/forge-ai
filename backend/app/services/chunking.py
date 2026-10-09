"""
Baseline deterministic source code chunker.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.pdf_extraction import ExtractedPage


@dataclass(frozen=True)
class ChunkData:
    """Represents a text chunk extracted from a source file."""

    chunk_index: int
    content: str
    start_line: int  # 1-indexed, inclusive
    end_line: int    # 1-indexed, inclusive


def chunk_source_code(
    content: str,
    chunk_size: int = 50,
    chunk_overlap: int = 10,
) -> list[ChunkData]:
    """Split source code into deterministic line-based chunks with overlap.

    Parameters:
      content: Raw text content of the file.
      chunk_size: Target number of lines per chunk (must be >= 1).
      chunk_overlap: Number of overlapping lines between consecutive chunks (must be >= 0 and < chunk_size).

    Returns:
      A list of ChunkData objects, each tracking its 0-indexed position and
      1-indexed start and end lines within the original content.
      Returns an empty list for empty or whitespace-only files.
    """
    if not content or not content.strip():
        return []

    if chunk_size < 1:
        raise ValueError("chunk_size must be at least 1 line.")
    if chunk_overlap < 0:
        raise ValueError("chunk_overlap must be non-negative.")
    if chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be strictly less than chunk_size.")

    # Split lines preserving text structure (splitlines without trailing newlines)
    lines = content.splitlines()
    total_lines = len(lines)

    if total_lines == 0:
        return []

    # If the file fits within a single chunk
    if total_lines <= chunk_size:
        return [
            ChunkData(
                chunk_index=0,
                content=content,
                start_line=1,
                end_line=total_lines,
            )
        ]

    chunks: list[ChunkData] = []
    step = chunk_size - chunk_overlap
    start_idx = 0
    chunk_idx = 0

    while start_idx < total_lines:
        end_idx = min(start_idx + chunk_size, total_lines)
        chunk_lines = lines[start_idx:end_idx]
        chunk_content = "\n".join(chunk_lines)

        chunks.append(
            ChunkData(
                chunk_index=chunk_idx,
                content=chunk_content,
                start_line=start_idx + 1,  # 1-indexed
                end_line=end_idx,          # 1-indexed, inclusive
            )
        )

        chunk_idx += 1

        # If this chunk reached or covered the end of the file, we are done
        if end_idx >= total_lines:
            break

        start_idx += step

    return chunks


@dataclass(frozen=True)
class KnowledgeChunkData:
    """Represents a text chunk extracted from an engineering knowledge document."""

    chunk_index: int
    content: str
    page_number: int | None = None


def chunk_knowledge_document(
    pages: list["ExtractedPage"],
    max_chunk_chars: int = 1000,
    overlap_chars: int = 150,
) -> list[KnowledgeChunkData]:
    """Split extracted knowledge document pages into deterministic chunks preserving page metadata.

    Parameters:
      pages: List of ExtractedPage objects (page_number, text).
      max_chunk_chars: Maximum character length per chunk (must be >= 100).
      overlap_chars: Number of overlapping characters between chunks (must be >= 0 and < max_chunk_chars).

    Returns:
      A list of KnowledgeChunkData objects with monotonic chunk indexes and
      accurate 1-indexed page numbers.
    """
    if not pages:
        return []

    if max_chunk_chars < 100:
        raise ValueError("max_chunk_chars must be at least 100 characters.")
    if overlap_chars < 0:
        raise ValueError("overlap_chars must be non-negative.")
    if overlap_chars >= max_chunk_chars:
        raise ValueError("overlap_chars must be strictly less than max_chunk_chars.")

    chunks: list[KnowledgeChunkData] = []
    chunk_idx = 0

    for page in pages:
        text = page.text.strip()
        if not text:
            continue

        # If page text fits within a single chunk
        if len(text) <= max_chunk_chars:
            chunks.append(
                KnowledgeChunkData(
                    chunk_index=chunk_idx,
                    content=text,
                    page_number=page.page_number,
                )
            )
            chunk_idx += 1
            continue

        # Page text exceeds max_chunk_chars: split with overlap at word boundaries
        start = 0
        text_len = len(text)

        while start < text_len:
            end = min(start + max_chunk_chars, text_len)

            # Try to avoid splitting inside a word if not at the end of the text
            if end < text_len:
                boundary = text.rfind("\n", start, end)
                if boundary == -1 or boundary <= start:
                    boundary = text.rfind(" ", start, end)
                if boundary > start:
                    end = boundary

            chunk_content = text[start:end].strip()
            if chunk_content:
                chunks.append(
                    KnowledgeChunkData(
                        chunk_index=chunk_idx,
                        content=chunk_content,
                        page_number=page.page_number,
                    )
                )
                chunk_idx += 1

            if end >= text_len:
                break

            start = max(start + 1, end - overlap_chars)

    return chunks

