"""
RAG orchestration service coordinating retrieval, context budgeting, prompt construction, and generation.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.rag import ChatResponse, Citation
from app.services.context_builder import ContextBuilder
from app.services.llm import LLMService, get_default_llm_service
from app.services.prompt_builder import PromptBuilder
from app.services.retrieval import RetrievalService


class RAGService:
    """Orchestrates the complete Retrieval-Augmented Generation (RAG) pipeline.

    Security & Architectural Invariants:
      1. Programmatic Citation Integrity:
         Citations are derived ONLY from ContextBuilder's included_chunks metadata (path, start_line, end_line).
         The LLM output is NEVER parsed for citations, preventing hallucinated or injected sources.
      2. Budget-Aware Citation Scope:
         Any chunk retrieved from the database but excluded by ContextBuilder's character budget
         is excluded from the final sources list.
      3. Swappable Dependencies:
         All sub-services (retrieval, context builder, prompt builder, LLM) are injected via constructor,
         enabling simple substitution for local or cloud LLMs without altering orchestration logic.
    """

    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        context_builder: ContextBuilder | None = None,
        prompt_builder: PromptBuilder | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()
        self.context_builder = context_builder or ContextBuilder()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.llm_service = llm_service or get_default_llm_service()

    async def answer_question(
        self,
        repository_id: UUID,
        question: str,
        db: AsyncSession,
        top_k: int = settings.rag_top_k,
        max_context_chars: int = settings.rag_max_context_chars,
    ) -> ChatResponse:
        """Answer a user question regarding the repository code using RAG.

        Args:
            repository_id: Authoritative UUID of the repository.
            question: User question string.
            db: Database session.
            top_k: Maximum number of chunks to retrieve.
            max_context_chars: Character budget for the context string.

        Returns:
            ChatResponse containing the LLM-generated answer and programmatic citations.
        """
        # Step 1: Semantic retrieval with repository isolation
        retrieved_chunks = await self.retrieval_service.search(
            repository_id=repository_id,
            query=question,
            db=db,
            top_k=top_k,
        )

        # Step 2: Assemble context within character budget
        context_result = self.context_builder.build(
            chunks=retrieved_chunks,
            max_chars=max_context_chars,
        )

        # Step 3: Construct prompt with untrusted data boundaries
        prompt = self.prompt_builder.build_prompt(
            question=question,
            context_text=context_result.context_text,
        )

        # Step 4: Generate answer text using LLMService
        answer_text = await self.llm_service.generate(prompt)

        # Step 5: Programmatically extract citations solely from included_chunks
        seen_citations: set[tuple[str, int, int]] = set()
        citations: list[Citation] = []

        for chunk in context_result.included_chunks:
            citation_key = (chunk.path, chunk.start_line, chunk.end_line)
            if citation_key not in seen_citations:
                seen_citations.add(citation_key)
                citations.append(
                    Citation(
                        path=chunk.path,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                    )
                )

        return ChatResponse(
            answer=answer_text,
            sources=citations,
        )


def get_default_rag_service() -> RAGService:
    """Factory to provide the active RAG service."""
    return RAGService()
