"""
Repository code retrieval service using PostgreSQL + pgvector.
"""

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.rag import ChunkRetrievalResult
from app.services.embedding import EmbeddingService, get_default_embedding_service

logger = logging.getLogger(__name__)


class RetrievalError(Exception):
    """Base exception for code retrieval operations."""
    pass


class RepositoryNotFoundError(RetrievalError):
    """Raised when the specified repository ID does not exist."""
    pass


class RepositoryNotReadyForSearchError(RetrievalError):
    """Raised when the repository has not completed ingestion."""
    pass


class RetrievalService:
    """Performs semantic vector similarity searches against indexed repository chunks in PostgreSQL.

    Security & Correctness Invariants:
      1. Mathematical Correctness:
         - Cosine distance: distance = CodeChunk.embedding.cosine_distance(query_vector)
         - Cosine similarity: similarity = 1 - distance in [0.0, 1.0] for normalized embeddings.
         - Ranking, thresholding, and top_k limiting are executed entirely in PostgreSQL.
      2. Repository Isolation:
         - The SQL query strictly joins CodeFile and filters on CodeFile.repository_id == repository_id.
         - Chunks from other repositories can never be accessed or returned.
      3. Index State Resilience:
         - If a completed repository has not yet been indexed or contains no matching chunks,
           returns an empty list cleanly without errors.
    """

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.embedding_service = embedding_service or get_default_embedding_service()

    async def search(
        self,
        repository_id: UUID,
        query: str,
        db: AsyncSession,
        top_k: int = settings.rag_top_k,
        similarity_threshold: float | None = None,
    ) -> list[ChunkRetrievalResult]:
        """Perform semantic search for code chunks matching the query within a repository.

        Args:
            repository_id: Authoritative UUID of the target repository.
            query: Natural language or code search query string.
            db: Active async database session.
            top_k: Maximum number of chunks to return (enforced at DB level via LIMIT).
            similarity_threshold: Optional minimum cosine similarity in [0.0, 1.0].

        Returns:
            List of ChunkRetrievalResult objects ranked by cosine similarity descending.

        Raises:
            RepositoryNotFoundError: If repository_id does not exist.
            RepositoryNotReadyForSearchError: If repository ingestion is not COMPLETED.
        """
        # Step 1: Validate repository existence and lifecycle status
        repo = await db.get(Repository, repository_id)
        if repo is None:
            raise RepositoryNotFoundError(f"Repository with ID '{repository_id}' not found.")

        if repo.status != IngestionStatus.COMPLETED:
            raise RepositoryNotReadyForSearchError(
                f"Repository ingestion status is '{repo.status.value}'. "
                "Ingestion must be completed before performing semantic search."
            )

        # Step 2: Generate embedding for the query string
        query_embeddings = await self.embedding_service.get_embeddings([query])
        if not query_embeddings:
            return []
        query_vector = query_embeddings[0]

        # Step 3: Construct database-level pgvector similarity query
        # pgvector's cosine_distance returns 1 - cosine_similarity for normalized vectors.
        distance_expr = CodeChunk.embedding.cosine_distance(query_vector)
        similarity_expr = (1.0 - distance_expr).label("similarity")

        stmt = (
            select(CodeChunk, CodeFile.path, similarity_expr)
            .join(CodeFile, CodeChunk.file_id == CodeFile.id)
            .where(CodeFile.repository_id == repository_id)
        )

        # Apply optional similarity threshold at database level
        if similarity_threshold is not None:
            stmt = stmt.where((1.0 - distance_expr) >= similarity_threshold)

        # Order by cosine distance ascending (closest / most similar first) and apply limit
        stmt = stmt.order_by(distance_expr.asc()).limit(top_k)

        res = await db.execute(stmt)
        rows = res.all()

        results: list[ChunkRetrievalResult] = []
        for chunk, path, sim in rows:
            # Clamp float for display precision within [0.0, 1.0]
            sim_score = max(0.0, min(1.0, float(sim)))
            results.append(
                ChunkRetrievalResult(
                    chunk_id=chunk.id,
                    file_id=chunk.file_id,
                    path=path,
                    content=chunk.content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    similarity=sim_score,
                )
            )

        return results
