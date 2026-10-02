"""
Orchestration service for Knowledge-Guided Code Analysis.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.repository import IngestionStatus, Repository
from app.schemas.analysis import (
    AnalysisResponse,
    AnalysisSource,
    CodeScope,
    CodeScopeType,
)
from app.schemas.rag import ChunkRetrievalResult
from app.services.agent_state import SourceRegistry
from app.services.analysis_prompt_builder import KnowledgeAnalysisPromptBuilder
from app.services.knowledge_retrieval import (
    KnowledgeRetrievalResult,
    KnowledgeRetrievalService,
)
from app.services.llm import LLMService, get_default_llm_service
from app.services.retrieval import RetrievalService

logger = logging.getLogger(__name__)


class AnalysisError(Exception):
    """Base exception for analysis orchestration errors."""
    pass


class AnalysisRepositoryNotFoundError(AnalysisError):
    """Raised when the specified repository does not exist."""
    pass


class AnalysisRepositoryNotReadyError(AnalysisError):
    """Raised when the repository has not completed ingestion and indexing."""
    pass


class AnalysisKnowledgeNotFoundError(AnalysisError):
    """Raised when the specified engineering knowledge scope does not exist."""
    pass


class AnalysisKnowledgeNotReadyError(AnalysisError):
    """Raised when the knowledge scope is in a failed or unready state."""
    pass


class InvalidCodeScopeError(AnalysisError):
    """Raised when code_scope arguments are malformed or invalid."""
    pass


class FileNotFoundInRepositoryError(AnalysisError):
    """Raised when the targeted file does not belong to the repository."""
    pass


class KnowledgeGuidedAnalysisService:
    """Orchestrates multi-domain retrieval (code + knowledge) and grounded LLM analysis."""

    def __init__(
        self,
        retrieval_service: RetrievalService | None = None,
        knowledge_retrieval_service: KnowledgeRetrievalService | None = None,
        prompt_builder: KnowledgeAnalysisPromptBuilder | None = None,
        llm_service: LLMService | None = None,
    ) -> None:
        self.retrieval_service = retrieval_service or RetrievalService()
        self.knowledge_retrieval_service = (
            knowledge_retrieval_service or KnowledgeRetrievalService()
        )
        self.prompt_builder = prompt_builder or KnowledgeAnalysisPromptBuilder()
        self.llm_service = llm_service or get_default_llm_service()

    async def analyze(
        self,
        repository_id: UUID,
        knowledge_id: UUID,
        code_scope: CodeScope,
        question: str,
        db: AsyncSession,
        top_k_repo: int = 5,
        top_k_knowledge: int = 5,
    ) -> AnalysisResponse:
        """Execute knowledge-guided code analysis with strict scope isolation and verified citations.

        Workflow:
          1. Validate repository exists and is COMPLETED.
          2. Validate engineering knowledge exists and is not FAILED.
          3. Validate code_scope (repository or file) and verify file ownership.
          4. Retrieve repository evidence based on code_scope.
          5. Retrieve knowledge evidence strictly filtered by knowledge_id.
          6. Budget and format dual-evidence context, registering citations.
          7. Invoke LLM with anti-hallucination prompt.
          8. Enforce grounding guard and return authoritative citations.
        """
        # Step 1: Validate repository
        repo = await db.get(Repository, repository_id)
        if repo is None:
            raise AnalysisRepositoryNotFoundError(f"Repository '{repository_id}' not found.")
        if repo.status != IngestionStatus.COMPLETED:
            raise AnalysisRepositoryNotReadyError(
                f"Repository ingestion status is '{repo.status.value}'. Must be completed."
            )

        # Step 2: Validate knowledge scope
        knowledge = await db.get(EngineeringKnowledge, knowledge_id)
        if knowledge is None:
            raise AnalysisKnowledgeNotFoundError(
                f"Engineering knowledge scope '{knowledge_id}' not found."
            )
        if knowledge.status == KnowledgeStatus.FAILED:
            raise AnalysisKnowledgeNotReadyError(
                f"Engineering knowledge scope '{knowledge.name}' is in a FAILED state."
            )

        # Step 3: Validate code scope
        normalized_path: str | None = None
        if code_scope.type == CodeScopeType.FILE:
            if not code_scope.path or not code_scope.path.strip():
                raise InvalidCodeScopeError("A file path must be specified when code_scope is 'file'.")
            normalized_path = code_scope.path.strip().replace("\\", "/")

            # Verify file belongs to this repository
            file_stmt = select(CodeFile).where(
                CodeFile.repository_id == repository_id,
                CodeFile.path == normalized_path,
            )
            file_res = await db.execute(file_stmt)
            target_file = file_res.scalar_one_or_none()
            if target_file is None:
                raise FileNotFoundInRepositoryError(
                    f"File '{normalized_path}' was not found in repository '{repo.name}'."
                )

        clean_question = question.strip()

        # Step 4: Retrieve repository evidence
        repo_chunks: list[ChunkRetrievalResult] = []
        if code_scope.type == CodeScopeType.FILE and normalized_path is not None:
            # Semantic retrieval restricted specifically to the target file
            query_embeddings = await self.retrieval_service.embedding_service.get_embeddings([clean_question])
            if query_embeddings:
                query_vector = query_embeddings[0]
                distance_expr = CodeChunk.embedding.cosine_distance(query_vector)
                similarity_expr = (1.0 - distance_expr).label("similarity")

                file_chunks_stmt = (
                    select(CodeChunk, CodeFile.path, similarity_expr)
                    .join(CodeFile, CodeChunk.file_id == CodeFile.id)
                    .where(
                        CodeFile.repository_id == repository_id,
                        CodeFile.path == normalized_path,
                    )
                    .order_by(distance_expr.asc())
                    .limit(top_k_repo)
                )
                file_chunks_res = await db.execute(file_chunks_stmt)
                repo_chunks = [
                    ChunkRetrievalResult(
                        chunk_id=chunk.id,
                        file_id=chunk.file_id,
                        path=p,
                        content=chunk.content,
                        start_line=chunk.start_line,
                        end_line=chunk.end_line,
                        similarity=max(0.0, min(1.0, float(sim))),
                    )
                    for chunk, p, sim in file_chunks_res.all()
                ]
        else:
            # Whole-repository hybrid search
            repo_chunks = await self.retrieval_service.search(
                repository_id=repository_id,
                query=clean_question,
                db=db,
                top_k=top_k_repo,
            )

        # Step 5: Retrieve engineering knowledge evidence
        knowledge_chunks: list[KnowledgeRetrievalResult] = []
        try:
            knowledge_chunks = await self.knowledge_retrieval_service.retrieve(
                knowledge_id=knowledge_id,
                query=clean_question,
                db=db,
                top_k=top_k_knowledge,
            )
        except Exception as exc:
            logger.warning("Knowledge retrieval yielded error for scope %s: %s", knowledge_id, exc)
            knowledge_chunks = []

        # Step 6: Budget context and format prompt
        registry = SourceRegistry()
        context_result = self.prompt_builder.build(
            question=clean_question,
            repo_chunks=repo_chunks,
            knowledge_chunks=knowledge_chunks,
            registry=registry,
        )

        # Step 7: Invoke LLM
        answer = await self.llm_service.generate(context_result.prompt)

        # Step 8: Grounding Guard
        # If the LLM explicitly declared that one or both domains lacked sufficient evidence,
        # adjust citations so we never attribute unverified claims.
        lower_answer = answer.lower()
        final_sources: list[AnalysisSource] = []

        no_repo_evidence = (
            not repo_chunks
            or "could not find enough relevant repository evidence" in lower_answer
            or "no relevant repository context" in lower_answer
        )
        no_knowledge_evidence = (
            not knowledge_chunks
            or "does not provide enough evidence to support a recommendation" in lower_answer
            or "no relevant engineering knowledge" in lower_answer
        )

        for src in context_result.sources:
            if src.type == "repository" and no_repo_evidence:
                continue
            if src.type == "knowledge" and no_knowledge_evidence:
                continue
            final_sources.append(src)

        return AnalysisResponse(
            answer=answer,
            sources=final_sources,
        )
