"""
Repository code retrieval service combining pgvector semantic search,
PostgreSQL lexical matching, path/filename relevance, and Reciprocal Rank Fusion (RRF).
"""

import logging
import re
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.rag import ChunkRetrievalResult
from app.services.embedding import EmbeddingService, get_default_embedding_service

logger = logging.getLogger(__name__)

# Common conversational and questioning stop words that carry minimal code-search discrimination
STOPWORDS: set[str] = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or", "is", "are", "was", "were",
    "where", "how", "what", "which", "who", "whom", "this", "that", "these", "those", "it", "its",
    "does", "do", "did", "can", "could", "should", "would", "be", "been", "being", "have", "has",
    "had", "by", "with", "from", "as", "into", "handled", "rendered", "configured", "implemented",
    "defined", "created", "used", "using", "here", "there", "about", "show", "tell", "explain",
}

LOCK_FILE_PATTERNS: tuple[str, ...] = (
    "%package-lock.json%",
    "%yarn.lock%",
    "%pnpm-lock.yaml%",
    "%Cargo.lock%",
    "%poetry.lock%",
    "%composer.lock%",
    "%Gemfile.lock%",
    "%components.json%",
    "%tsconfig.tsbuildinfo%",
)

NOISE_FILE_PATTERNS: tuple[str, ...] = (
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "cargo.lock",
    "poetry.lock",
    "composer.lock",
    "gemfile.lock",
    "components.json",
    "tsconfig.tsbuildinfo",
)


def extract_query_tokens(query: str) -> list[str]:
    """Extract code-relevant keywords and identifiers from a user query.

    Splits camelCase, snake_case, strips stop words, generates stems,
    and returns sanitized alphanumeric tokens safe for PostgreSQL full-text search.
    """
    clean_query = query.strip()
    if not clean_query:
        return []

    # Split camelCase / PascalCase into sub-tokens while preserving original
    # e.g. "getFileContent" -> "getFileContent", "get", "File", "Content"
    words: list[str] = []
    raw_words = re.findall(r"[A-Za-z0-9_]+", clean_query)
    for w in raw_words:
        words.append(w)
        # Split on uppercase transitions if camelCase
        parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?=[A-Z][a-z]|\b)", w)
        if len(parts) > 1:
            words.extend(parts)
        # Split on underscores if snake_case
        if "_" in w:
            words.extend([p for p in w.split("_") if p])

    # Lowercase, filter stopwords and short tokens, generate stem variants
    tokens: list[str] = []
    seen: set[str] = set()
    for w in words:
        clean = re.sub(r"[^a-zA-Z0-9_]", "", w).lower()
        if len(clean) >= 2 and clean not in STOPWORDS and clean not in seen:
            seen.add(clean)
            tokens.append(clean)
            # Add simple singular variation if word ends in 's'
            if clean.endswith("s") and len(clean) > 3 and not clean.endswith("ss"):
                singular = clean[:-1]
                if singular not in seen and singular not in STOPWORDS:
                    seen.add(singular)
                    tokens.append(singular)

    return tokens


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
    """Performs hybrid code retrieval against indexed repository chunks in PostgreSQL.

    Security & Correctness Invariants:
      1. Repository Isolation:
         All SQL queries strictly join CodeFile and filter on CodeFile.repository_id == repository_id.
         Chunks from other repositories can never be accessed or returned.
      2. Multi-Signal Fusion (Reciprocal Rank Fusion):
         Combines semantic vector proximity, lexical code-text matching, and path/filename relevance
         via rank-based reciprocal fusion, avoiding scale-calibration pitfalls.
      3. Noise Suppression:
         Lock and dependency manifest files are deprioritized relative to source code files.
      4. Index State Resilience:
         If a completed repository has not yet been indexed or contains no matching chunks,
         returns an empty list cleanly without errors.
    """

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.embedding_service = embedding_service or get_default_embedding_service()

    async def retrieve_semantic_candidates(
        self,
        repository_id: UUID,
        query_vector: list[float],
        db: AsyncSession,
        limit: int = settings.retrieval_semantic_candidates,
        similarity_threshold: float | None = None,
    ) -> list[tuple[CodeChunk, str, float]]:
        """Retrieve top semantic candidates using pgvector cosine distance."""
        distance_expr = CodeChunk.embedding.cosine_distance(query_vector)
        similarity_expr = (1.0 - distance_expr).label("similarity")

        stmt = (
            select(CodeChunk, CodeFile.path, similarity_expr)
            .join(CodeFile, CodeChunk.file_id == CodeFile.id)
            .where(CodeFile.repository_id == repository_id)
        )
        if similarity_threshold is not None:
            stmt = stmt.where((1.0 - distance_expr) >= similarity_threshold)

        stmt = stmt.order_by(distance_expr.asc()).limit(limit)
        res = await db.execute(stmt)
        return [(chunk, path, max(0.0, min(1.0, float(sim)))) for chunk, path, sim in res.all()]

    async def retrieve_lexical_candidates(
        self,
        repository_id: UUID,
        tokens: list[str],
        db: AsyncSession,
        limit: int = settings.retrieval_lexical_candidates,
    ) -> list[tuple[CodeChunk, str, float]]:
        """Retrieve top lexical candidates using PostgreSQL full-text search with code-aware rescoring."""
        if not tokens:
            return []

        search_tokens = [t for t in tokens if len(t) >= 3]
        if not search_tokens:
            search_tokens = tokens

        tsquery_str = " | ".join(search_tokens)
        try:
            rank_expr = func.ts_rank_cd(
                func.to_tsvector("simple", CodeChunk.content),
                func.to_tsquery("simple", tsquery_str),
            )
            stmt = (
                select(CodeChunk, CodeFile.path, rank_expr.label("lex_rank"))
                .join(CodeFile, CodeChunk.file_id == CodeFile.id)
                .where(
                    CodeFile.repository_id == repository_id,
                    func.to_tsvector("simple", CodeChunk.content).op("@@")(
                        func.to_tsquery("simple", tsquery_str)
                    ),
                )
                .order_by(rank_expr.desc())
                .limit(limit * 2)  # retrieve candidate pool to rescore in Python
            )
            res = await db.execute(stmt)
            raw_candidates = res.all()
            if not raw_candidates:
                return []

            # Deterministic code-aware rescoring in Python:
            # - Boost chunks containing the longest identifier/token (e.g. CardSpotlight, getFileContent)
            # - Boost chunks containing multiple distinct query tokens (e.g. both 'card' and 'spotlight')
            # - Boost definition/declaration patterns (export const X, function X, class X, def X)
            longest_token = max(tokens, key=len).lower() if tokens else ""
            scored_candidates: list[tuple[CodeChunk, str, float]] = []

            for chunk, path, pg_rank in raw_candidates:
                c_lower = chunk.content.lower()
                matched_tokens = [t for t in tokens if t in c_lower]
                score = float(pg_rank)

                # Distinct tokens bonus
                score += len(matched_tokens) * 1.5

                # Longest token / exact identifier bonus (for len >= 5)
                if longest_token and len(longest_token) >= 5 and longest_token in c_lower:
                    score += 5.0

                # Symbol definition / implementation bonus
                if longest_token and any(
                    f"{decl} {longest_token}" in c_lower or f"{decl} {tokens[0].lower()}" in c_lower
                    for decl in ("const", "function", "class", "export const", "export function", "export class", "def", "interface", "type")
                ):
                    score += 4.0

                scored_candidates.append((chunk, path, score))

            scored_candidates.sort(key=lambda x: x[2], reverse=True)
            return scored_candidates[:limit]
        except Exception as e:
            logger.warning("Lexical search query failed for tokens %s: %s", tokens, e)
            return []

    async def retrieve_path_candidates(
        self,
        repository_id: UUID,
        tokens: list[str],
        db: AsyncSession,
        limit: int = settings.retrieval_path_candidates,
    ) -> list[tuple[CodeChunk, str, float]]:
        """Retrieve candidate chunks from files whose path or filename matches query tokens."""
        # Only use tokens with length >= 3 for path filtering to avoid noisy 2-letter matches
        path_tokens = [t for t in tokens if len(t) >= 3]
        if not path_tokens:
            return []

        path_filters = [CodeFile.path.ilike(f"%{t}%") for t in path_tokens]
        lock_filters = [~CodeFile.path.ilike(pattern) for pattern in LOCK_FILE_PATTERNS]

        try:
            stmt = (
                select(CodeChunk, CodeFile.path)
                .join(CodeFile, CodeChunk.file_id == CodeFile.id)
                .where(
                    CodeFile.repository_id == repository_id,
                    or_(*path_filters),
                    *lock_filters,
                )
                .order_by(CodeChunk.chunk_index.asc())
                .limit(limit * 2)  # retrieve pool to score in Python
            )
            res = await db.execute(stmt)
            rows = res.all()
            if not rows:
                return []

            # Score each path candidate based on token overlap in filename vs directory
            longest_token = max(path_tokens, key=len).lower() if path_tokens else ""
            scored_candidates: list[tuple[CodeChunk, str, float]] = []
            for chunk, path in rows:
                path_lower = path.lower()
                filename = path_lower.split("/")[-1]
                score = 0.0
                matches_in_filename = 0
                for t in path_tokens:
                    if t in filename:
                        score += 3.0  # high weight for filename match
                        matches_in_filename += 1
                    elif t in path_lower:
                        score += 1.0  # medium weight for directory match

                # Extra bonus for matching multiple tokens in filename or the longest identifier
                if matches_in_filename > 1:
                    score += 2.0
                if longest_token and len(longest_token) >= 5 and longest_token in filename:
                    score += 3.0

                # Slightly favor earlier chunks (component root / exports)
                chunk_penalty = min(0.5, chunk.chunk_index * 0.05)
                final_score = max(0.1, score - chunk_penalty)
                scored_candidates.append((chunk, path, final_score))

            scored_candidates.sort(key=lambda x: x[2], reverse=True)
            return scored_candidates[:limit]
        except Exception as e:
            logger.warning("Path search query failed for tokens %s: %s", path_tokens, e)
            return []

    def fuse_and_rerank(
        self,
        semantic_candidates: list[tuple[CodeChunk, str, float]],
        lexical_candidates: list[tuple[CodeChunk, str, float]],
        path_candidates: list[tuple[CodeChunk, str, float]],
        top_k: int = settings.rag_top_k,
        similarity_threshold: float | None = None,
        rrf_k: int = settings.rrf_k,
        weight_semantic: float = settings.rrf_weight_semantic,
        weight_lexical: float = settings.rrf_weight_lexical,
        weight_path: float = settings.rrf_weight_path,
    ) -> list[ChunkRetrievalResult]:
        """Combine multi-channel candidate lists using Reciprocal Rank Fusion (RRF)."""
        # Build rank lookups (1-indexed)
        sem_ranks: dict[UUID, int] = {chunk.id: idx + 1 for idx, (chunk, _, _) in enumerate(semantic_candidates)}
        lex_ranks: dict[UUID, int] = {chunk.id: idx + 1 for idx, (chunk, _, _) in enumerate(lexical_candidates)}
        path_ranks: dict[UUID, int] = {chunk.id: idx + 1 for idx, (chunk, _, _) in enumerate(path_candidates)}

        # Collect unique chunks
        chunk_map: dict[UUID, tuple[CodeChunk, str]] = {}
        for chunk, path, _ in semantic_candidates:
            chunk_map[chunk.id] = (chunk, path)
        for chunk, path, _ in lexical_candidates:
            chunk_map[chunk.id] = (chunk, path)
        for chunk, path, _ in path_candidates:
            chunk_map[chunk.id] = (chunk, path)

        if not chunk_map:
            return []

        # Compute RRF score for each unique candidate
        scores: dict[UUID, float] = {}
        for cid, (chunk, path) in chunk_map.items():
            s_contrib = (weight_semantic / (rrf_k + sem_ranks[cid])) if cid in sem_ranks else 0.0
            l_contrib = (weight_lexical / (rrf_k + lex_ranks[cid])) if cid in lex_ranks else 0.0
            p_contrib = (weight_path / (rrf_k + path_ranks[cid])) if cid in path_ranks else 0.0

            total_score = s_contrib + l_contrib + p_contrib

            # Apply deprioritization penalty to lock files and config manifests
            # so authentic source code files take precedence
            path_lower = path.lower()
            if any(term in path_lower for term in NOISE_FILE_PATTERNS):
                total_score *= 0.1

            scores[cid] = total_score

        # Sort descending by fused RRF score
        sorted_cids = sorted(scores.keys(), key=lambda cid: scores[cid], reverse=True)
        max_score = scores[sorted_cids[0]] if sorted_cids else 1.0

        results: list[ChunkRetrievalResult] = []
        for cid in sorted_cids:
            chunk, path = chunk_map[cid]
            # Normalize score relative to top candidate for a stable [0.0, 1.0] scale
            norm_score = max(0.0, min(1.0, float(scores[cid] / max_score))) if max_score > 0 else 0.0

            # Apply optional threshold filter
            if similarity_threshold is not None and norm_score < similarity_threshold:
                continue

            results.append(
                ChunkRetrievalResult(
                    chunk_id=chunk.id,
                    file_id=chunk.file_id,
                    path=path,
                    content=chunk.content,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    similarity=norm_score,
                )
            )
            if len(results) >= top_k:
                break

        return results

    async def search(
        self,
        repository_id: UUID,
        query: str,
        db: AsyncSession,
        top_k: int = settings.rag_top_k,
        similarity_threshold: float | None = None,
    ) -> list[ChunkRetrievalResult]:
        """Perform hybrid retrieval combining semantic, lexical, and path relevance with RRF.

        Args:
            repository_id: Authoritative UUID of the target repository.
            query: Natural language or code search query string.
            db: Active async database session.
            top_k: Maximum number of chunks to return.
            similarity_threshold: Optional minimum normalized score in [0.0, 1.0].

        Returns:
            List of ChunkRetrievalResult objects ranked by fused relevance descending.

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

        clean_query = query.strip()
        if not clean_query:
            return []

        # Step 2: Extract keywords for lexical and path signals
        tokens = extract_query_tokens(clean_query)

        # Step 3: Generate embedding for semantic signal
        query_embeddings = await self.embedding_service.get_embeddings([clean_query])
        query_vector = query_embeddings[0] if query_embeddings else None

        # Step 4: Multi-channel candidate retrieval
        semantic_candidates: list[tuple[CodeChunk, str, float]] = []
        if query_vector is not None:
            semantic_candidates = await self.retrieve_semantic_candidates(
                repository_id=repository_id,
                query_vector=query_vector,
                db=db,
                limit=settings.retrieval_semantic_candidates,
                similarity_threshold=similarity_threshold,
            )

        lexical_candidates = await self.retrieve_lexical_candidates(
            repository_id=repository_id,
            tokens=tokens,
            db=db,
            limit=settings.retrieval_lexical_candidates,
        )

        path_candidates = await self.retrieve_path_candidates(
            repository_id=repository_id,
            tokens=tokens,
            db=db,
            limit=settings.retrieval_path_candidates,
        )

        # Step 5: Rank-based fusion and deduplication
        return self.fuse_and_rerank(
            semantic_candidates=semantic_candidates,
            lexical_candidates=lexical_candidates,
            path_candidates=path_candidates,
            top_k=top_k,
            similarity_threshold=similarity_threshold,
        )
