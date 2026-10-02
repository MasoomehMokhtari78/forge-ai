"""
Context builder and prompt constructor for Knowledge-Guided Analysis.
"""

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from app.core.config import settings
from app.schemas.analysis import AnalysisSource
from app.schemas.rag import ChunkRetrievalResult
from app.services.agent_state import SourceRegistry
from app.services.knowledge_retrieval import KnowledgeRetrievalResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AnalysisContextResult:
    """Formatted context text with registered authoritative sources."""

    prompt: str
    sources: list[AnalysisSource]


class KnowledgeAnalysisPromptBuilder:
    """Builds two-evidence prompts enforcing strict character budgets and grounding invariants.

    Invariants:
      1. Dual Evidence Budgeting:
         Repository evidence and Engineering Knowledge share the configured context budget
         (60% repository, 40% knowledge) to prevent starvation or prompt explosion.
      2. Source Attribution:
         Every chunk admitted into context is registered with SourceRegistry and assigned
         a stable source ID (e.g. 'src_1', 'src_2').
      3. Authoritative Citation Scope:
         Only chunks that successfully fit within the budget and enter the prompt are
         returned as verified citations.
      4. Anti-Hallucination Directives:
         Explicit system instructions mandate distinguishing repository facts from
         knowledge reference facts, and forbid fabricating patterns or repository code.
    """

    SYSTEM_INSTRUCTIONS = (
        "You are ForgeAI, an expert software architecture and engineering assistant.\n"
        "Your task is to analyze repository code in the context of user-provided engineering knowledge.\n\n"
        "Important Security & Grounding Rules:\n"
        "1. Distinguish clearly between:\n"
        "   - Repository facts: What the retrieved repository code actually shows.\n"
        "   - Knowledge facts: What the retrieved engineering reference actually says.\n"
        "   - Recommendations / Reasoning: Your conclusion connecting the two.\n"
        "2. Base your answer ONLY on the supplied repository evidence and engineering knowledge below.\n"
        "3. Strict Accuracy Prohibitions:\n"
        "   - Never invent or hallucinate patterns, rules, or concepts not present in the engineering reference.\n"
        "   - Never invent repository code, files, classes, or behaviors not present in the repository evidence.\n"
        "   - Never claim that an unsupported pattern exists in the engineering reference.\n"
        "   - Never present a recommendation or hypothesis as an established fact.\n"
        "4. Handling Insufficient Evidence:\n"
        "   - If the engineering knowledge does not contain relevant information for the question, state:\n"
        "     'The selected knowledge scope does not provide enough evidence to support a recommendation for this question.'\n"
        "   - If the repository evidence is insufficient, state:\n"
        "     'I could not find enough relevant repository evidence to make a grounded recommendation about this implementation.'\n"
        "5. Reference sources using their assigned source IDs (e.g. [src_1], [src_2]) when making claims."
    )

    def __init__(self, default_max_chars: int | None = None) -> None:
        self.max_chars = default_max_chars or settings.rag_max_context_chars

    def build(
        self,
        question: str,
        repo_chunks: list[ChunkRetrievalResult],
        knowledge_chunks: list[KnowledgeRetrievalResult],
        registry: SourceRegistry,
    ) -> AnalysisContextResult:
        """Format repository and knowledge evidence into a budgeted, grounded prompt.

        Args:
            question: The user's software engineering query.
            repo_chunks: Ranked code chunks from repository retrieval.
            knowledge_chunks: Ranked chunks from engineering knowledge retrieval.
            registry: SourceRegistry to register admitted chunks and issue stable source IDs.

        Returns:
            AnalysisContextResult with the complete prompt and verified citations.
        """
        repo_budget = int(self.max_chars * 0.60)
        knowledge_budget = self.max_chars - repo_budget

        verified_sources: list[AnalysisSource] = []

        # --- Format Repository Evidence ---
        repo_blocks: list[str] = []
        current_repo_len = 0
        separator = "\n\n" + ("-" * 30) + "\n\n"

        for chunk in repo_chunks:
            source_id = registry.register(
                path=chunk.path,
                start_line=chunk.start_line,
                end_line=chunk.end_line,
                source_type="repository",
            )
            label = f"{chunk.path}:{chunk.start_line}-{chunk.end_line}"
            block = (
                f"[source {source_id}]\n"
                f"{label}\n"
                f"{chunk.content}"
            )
            sep_len = len(separator) if repo_blocks else 0
            candidate_len = current_repo_len + sep_len + len(block)

            if candidate_len <= repo_budget:
                repo_blocks.append(block)
                current_repo_len = candidate_len
                verified_sources.append(
                    AnalysisSource(
                        source_id=source_id,
                        type="repository",
                        label=label,
                        path=chunk.path,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                    )
                )
            else:
                # If first chunk exceeds budget, truncate deterministically
                if not repo_blocks:
                    header = f"[source {source_id}]\n{label}\n"
                    marker = "\n[...truncated to context budget...]"
                    overhead = len(header) + len(marker)
                    if repo_budget > overhead:
                        available = repo_budget - overhead
                        truncated_content = chunk.content[:available]
                        fitted_block = header + truncated_content + marker
                        repo_blocks.append(fitted_block)
                        current_repo_len = len(fitted_block)
                        verified_sources.append(
                            AnalysisSource(
                                source_id=source_id,
                                type="repository",
                                label=label,
                                path=chunk.path,
                                start_line=chunk.start_line,
                                end_line=chunk.end_line,
                            )
                        )
                continue

        repo_context = separator.join(repo_blocks) if repo_blocks else "(No relevant repository code chunks found)"

        # --- Format Engineering Knowledge Evidence ---
        knowledge_blocks: list[str] = []
        current_k_len = 0

        for k_chunk in knowledge_chunks:
            source_id = registry.register_knowledge(
                filename=k_chunk.filename,
                page_number=k_chunk.page_number,
                chunk_id=k_chunk.chunk_id,
            )
            label = (
                f"{k_chunk.filename}, page {k_chunk.page_number}"
                if k_chunk.page_number is not None
                else k_chunk.filename
            )
            block = (
                f"[source {source_id}]\n"
                f"{label}\n"
                f"{k_chunk.content}"
            )
            sep_len = len(separator) if knowledge_blocks else 0
            candidate_len = current_k_len + sep_len + len(block)

            if candidate_len <= knowledge_budget:
                knowledge_blocks.append(block)
                current_k_len = candidate_len
                verified_sources.append(
                    AnalysisSource(
                        source_id=source_id,
                        type="knowledge",
                        label=label,
                        path=k_chunk.filename,
                        page_number=k_chunk.page_number,
                    )
                )
            else:
                # Truncate first chunk if oversized
                if not knowledge_blocks:
                    header = f"[source {source_id}]\n{label}\n"
                    marker = "\n[...truncated to context budget...]"
                    overhead = len(header) + len(marker)
                    if knowledge_budget > overhead:
                        available = knowledge_budget - overhead
                        truncated_content = k_chunk.content[:available]
                        fitted_block = header + truncated_content + marker
                        knowledge_blocks.append(fitted_block)
                        current_k_len = len(fitted_block)
                        verified_sources.append(
                            AnalysisSource(
                                source_id=source_id,
                                type="knowledge",
                                label=label,
                                path=k_chunk.filename,
                                page_number=k_chunk.page_number,
                            )
                        )
                continue

        knowledge_context = (
            separator.join(knowledge_blocks)
            if knowledge_blocks
            else "(No relevant engineering knowledge found)"
        )

        # Assemble prompt
        clean_question = question.strip()
        prompt = (
            f"{self.SYSTEM_INSTRUCTIONS}\n\n"
            f"## Repository Evidence\n\n"
            f"{repo_context}\n\n"
            f"## Engineering Knowledge\n\n"
            f"{knowledge_context}\n\n"
            f"## User Question\n\n"
            f"{clean_question}"
        )

        return AnalysisContextResult(prompt=prompt, sources=verified_sources)
