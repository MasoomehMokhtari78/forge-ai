"""
Engineering knowledge retrieval service using pgvector similarity search.
"""

from dataclasses import dataclass
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.embedding import (
    EmbeddingError,
    EmbeddingService,
    get_default_embedding_service,
)
from app.services.engineering_knowledge import KnowledgeNotFoundError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KnowledgeRetrievalResult:
    """Represents a retrieved engineering knowledge chunk with location metadata and similarity score."""

    chunk_id: UUID
    knowledge_id: UUID
    document_id: UUID
    filename: str
    content: str
    page_number: int | None
    chunk_index: int
    similarity: float


class KnowledgeRetrievalService:
    """Retrieves relevant engineering knowledge chunks strictly scoped to a selected knowledge scope."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.embedding_service = embedding_service or get_default_embedding_service()

    async def retrieve(
        self,
        knowledge_id: UUID,
        query: str,
        db: AsyncSession,
        top_k: int = 5,
        similarity_threshold: float | None = None,
    ) -> list[KnowledgeRetrievalResult]:
        """Retrieve relevant knowledge chunks strictly within the specified knowledge scope.

        Security & Correctness Invariants:
          1. Strict Knowledge Scope Isolation:
             All queries filter on KnowledgeChunk.knowledge_id == knowledge_id.
             Chunks from other knowledge scopes can never be returned.
          2. Document State Verification:
             Only chunks belonging to COMPLETED documents are considered eligible.
          3. Semantic Vector Proximity:
             Uses pgvector cosine distance on normalized embeddings.

        Raises:
            KnowledgeNotFoundError: If knowledge_id does not exist.
        """
        # Step 1: Validate knowledge scope exists
        knowledge = await db.get(EngineeringKnowledge, knowledge_id)
        if knowledge is None:
            raise KnowledgeNotFoundError(
                f"Engineering knowledge scope '{knowledge_id}' not found."
            )

        clean_query = query.strip()
        if not clean_query:
            return []

        # Step 2: Generate embedding vector for query
        try:
            query_embeddings = await self.embedding_service.get_embeddings([clean_query])
        except EmbeddingError as err:
            logger.error("Embedding generation failed for knowledge query: %s", err)
            raise
        except Exception as exc:
            logger.exception("Unexpected error generating embedding for query: %s", exc)
            raise

        if not query_embeddings:
            return []
        query_vector = query_embeddings[0]

        # Step 3: pgvector similarity search strictly filtered by knowledge_id
        distance_expr = KnowledgeChunk.embedding.cosine_distance(query_vector)
        similarity_expr = (1.0 - distance_expr).label("similarity")

        stmt = (
            select(
                KnowledgeChunk,
                KnowledgeDocument.filename,
                similarity_expr,
            )
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(
                KnowledgeChunk.knowledge_id == knowledge_id,
                KnowledgeDocument.status == KnowledgeStatus.COMPLETED,
            )
        )

        if similarity_threshold is not None:
            stmt = stmt.where((1.0 - distance_expr) >= similarity_threshold)

        stmt = stmt.order_by(distance_expr.asc()).limit(top_k)

        res = await db.execute(stmt)
        rows = res.all()

        results: list[KnowledgeRetrievalResult] = []
        for chunk, filename, sim in rows:
            results.append(
                KnowledgeRetrievalResult(
                    chunk_id=chunk.id,
                    knowledge_id=chunk.knowledge_id,
                    document_id=chunk.document_id,
                    filename=filename,
                    content=chunk.content,
                    page_number=chunk.page_number,
                    chunk_index=chunk.chunk_index,
                    similarity=max(0.0, min(1.0, float(sim))),
                )
            )

        return results
