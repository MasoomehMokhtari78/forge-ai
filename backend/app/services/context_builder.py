"""
Context builder for RAG prompt construction with strict character budgeting.
"""

from dataclasses import dataclass

from app.core.config import settings
from app.schemas.rag import ChunkRetrievalResult


@dataclass(frozen=True)
class ContextBuildResult:
    """Result of context formatting, returning the budgeted text and included chunks."""

    context_text: str
    included_chunks: list[ChunkRetrievalResult]


class ContextBuilder:
    """Formats retrieved code chunks into structured context blocks enforcing a total character budget.

    Invariants:
      1. Complete Context Budgeting:
         The character limit (max_context_chars) applies to the complete formatted string,
         including source headers, separators, line annotations, and code contents.
      2. Complete Chunk Preservation:
         Chunks are included whole whenever they fit into the remaining budget.
         If adding the next chunk would exceed the budget, packing terminates.
      3. Oversized First Chunk Handling:
         If the very first chunk's formatted block exceeds the entire budget, it is
         deterministically truncated to fit within max_context_chars with an explicit marker.
      4. Authoritative Included Chunks:
         Only chunks that were actually included (or partially included) in context_text
         are returned in included_chunks. Chunks excluded due to budget are omitted.
    """

    def __init__(self, default_max_chars: int | None = None) -> None:
        self.default_max_chars = default_max_chars or settings.rag_max_context_chars

    @staticmethod
    def _format_chunk(source_index: int, chunk: ChunkRetrievalResult) -> str:
        """Format a single chunk into a standard structured block."""
        return (
            f"[Source {source_index}]\n"
            f"File: {chunk.path}\n"
            f"Lines: {chunk.start_line}-{chunk.end_line}\n\n"
            f"{chunk.content}"
        )

    def build(
        self,
        chunks: list[ChunkRetrievalResult],
        max_chars: int | None = None,
    ) -> ContextBuildResult:
        """Build structured context string from retrieved chunks within max_chars.

        Args:
            chunks: Ranked list of retrieved code chunks.
            max_chars: Maximum character budget for the entire context string.

        Returns:
            ContextBuildResult containing the assembled text and the exact list of
            chunks that were included.
        """
        budget = max_chars if max_chars is not None else self.default_max_chars

        if not chunks or budget <= 0:
            return ContextBuildResult(
                context_text="(No relevant code chunks found)",
                included_chunks=[],
            )

        separator = "\n\n" + ("-" * 40) + "\n\n"
        included_chunks: list[ChunkRetrievalResult] = []
        formatted_blocks: list[str] = []
        current_len = 0

        for i, chunk in enumerate(chunks, start=1):
            block = self._format_chunk(i, chunk)
            block_len = len(block)
            sep_len = len(separator) if formatted_blocks else 0
            candidate_len = current_len + sep_len + block_len

            if candidate_len <= budget:
                formatted_blocks.append(block)
                included_chunks.append(chunk)
                current_len = candidate_len
            else:
                # If this is the very first chunk and it cannot fit whole:
                if not formatted_blocks:
                    # Deterministically truncate the first chunk's code to fit within the budget
                    header = (
                        f"[Source {i}]\n"
                        f"File: {chunk.path}\n"
                        f"Lines: {chunk.start_line}-{chunk.end_line}\n\n"
                    )
                    truncation_marker = "\n[...truncated to context budget...]"
                    overhead = len(header) + len(truncation_marker)

                    if budget > overhead:
                        available_code_chars = budget - overhead
                        truncated_content = chunk.content[:available_code_chars]
                        fitted_block = header + truncated_content + truncation_marker
                        formatted_blocks.append(fitted_block)
                        included_chunks.append(chunk)
                    # If budget is smaller than even header + marker, nothing fits
                break

        if not formatted_blocks:
            return ContextBuildResult(
                context_text="(No relevant code chunks found)",
                included_chunks=[],
            )

        return ContextBuildResult(
            context_text=separator.join(formatted_blocks),
            included_chunks=included_chunks,
        )
