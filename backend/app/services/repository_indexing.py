"""
Repository code indexing service.
"""

from dataclasses import dataclass
import logging
from pathlib import Path
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.services.chunking import ChunkData, chunk_source_code
from app.services.embedding import EmbeddingError, EmbeddingService, get_default_embedding_service
from app.services.repository_files import DiscoveredFile, discover_repository_files

logger = logging.getLogger(__name__)


class IndexingError(Exception):
    """User-safe exception raised when indexing fails."""
    pass


class RepositoryNotFoundError(IndexingError):
    """Raised when the specified repository ID does not exist."""
    pass


class RepositoryNotReadyForIndexingError(IndexingError):
    """Raised when repository ingestion has not completed successfully."""
    pass


class RepositoryFilesNotAvailableError(IndexingError):
    """Raised when the cloned files are missing from the server filesystem."""
    pass


@dataclass(frozen=True)
class IndexingResult:
    """Summary of the indexing operation."""

    repository_id: UUID
    files_indexed: int
    chunks_created: int


class RepositoryIndexingService:
    """Indexes source files and chunks into PostgreSQL/pgvector."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.embedding_service = embedding_service or get_default_embedding_service()
        self.storage_root = Path(settings.repository_storage_path).resolve()
        self.chunk_size = settings.chunk_size
        self.chunk_overlap = settings.chunk_overlap
        self.max_file_size = settings.max_file_size_bytes

    async def index_repository(
        self,
        repository_id: UUID,
        db: AsyncSession,
    ) -> IndexingResult:
        """Execute deterministic and idempotent repository indexing.

        Workflow:
          1. Verify repository exists
          2. Verify repository ingestion is COMPLETED
          3. Verify cloned files exist locally
          4. Discover eligible files using Phase 2 discovery logic
          5. Read text contents and chunk into line-based segments
          6. Generate vector embeddings via EmbeddingService
          7. In a single atomic transaction:
             - Remove any previously indexed files/chunks for this repository
             - Persist fresh CodeFile and CodeChunk records
          8. Commit and return indexing metrics
        """
        # Step 1 & 2: Validate repository record and ingestion status
        repo = await db.get(Repository, repository_id)
        if repo is None:
            raise RepositoryNotFoundError(f"Repository with ID '{repository_id}' not found.")

        if repo.status != IngestionStatus.COMPLETED:
            raise RepositoryNotReadyForIndexingError(
                f"Repository ingestion status is '{repo.status.value}'. "
                "Ingestion must be completed before indexing."
            )

        # Step 3: Validate local directory
        repo_dir = (self.storage_root / str(repository_id)).resolve()
        if not repo_dir.is_dir() or not repo_dir.is_relative_to(self.storage_root):
            raise RepositoryFilesNotAvailableError(
                "Cloned repository files are not available on the server. "
                "Please re-ingest the repository."
            )

        # Step 4: Discover eligible files
        discovered_files: list[DiscoveredFile] = discover_repository_files(
            repo_dir,
            max_file_size_bytes=self.max_file_size,
        )
        logger.info("Indexing repository %s: discovered %d eligible files", repository_id, len(discovered_files))

        # Step 5: Read and chunk files
        file_chunk_pairs: list[tuple[DiscoveredFile, list[ChunkData]]] = []
        all_chunk_texts: list[str] = []

        for disc_file in discovered_files:
            file_path = repo_dir / disc_file.relative_path
            try:
                # Read text safely handling potential encoding issues
                content = file_path.read_text(encoding="utf-8", errors="replace")
            except Exception as exc:
                logger.warning("Skipping unreadable file %s: %s", disc_file.relative_path, exc)
                continue

            chunks = chunk_source_code(
                content=content,
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
            )

            file_chunk_pairs.append((disc_file, chunks))
            for c in chunks:
                all_chunk_texts.append(c.content)

        logger.info(
            "Repository %s: prepared %d chunks across %d files for embedding",
            repository_id,
            len(all_chunk_texts),
            len(file_chunk_pairs),
        )

        # Step 6: Generate vector embeddings in batches
        all_embeddings: list[list[float]] = []
        if all_chunk_texts:
            batch_size = 64
            for i in range(0, len(all_chunk_texts), batch_size):
                batch = all_chunk_texts[i : i + batch_size]
                try:
                    batch_embeddings = await self.embedding_service.get_embeddings(batch)
                except EmbeddingError as emb_err:
                    logger.error("Embedding generation failed for repository %s: %s", repository_id, emb_err)
                    raise IndexingError(f"Embedding generation failed: {emb_err}") from emb_err
                except Exception as exc:
                    logger.exception("Unexpected error during embedding generation for %s: %s", repository_id, exc)
                    raise IndexingError("An unexpected error occurred during embedding generation.") from exc

                all_embeddings.extend(batch_embeddings)

        # Step 7: Atomic persistence (Idempotent: replace previous indexing data)
        embedding_iter = iter(all_embeddings)
        total_files = 0
        total_chunks = 0

        try:
            # Delete any existing files for this repository (cascades to chunks)
            await db.execute(delete(CodeFile).where(CodeFile.repository_id == repository_id))

            for disc_file, chunks in file_chunk_pairs:
                code_file = CodeFile(
                    repository_id=repository_id,
                    path=disc_file.relative_path,
                    extension=disc_file.extension,
                    size_bytes=disc_file.size_bytes,
                )
                db.add(code_file)
                # Flush to generate code_file.id for foreign keys
                await db.flush()
                total_files += 1

                for chunk_data in chunks:
                    chunk_embedding = next(embedding_iter)
                    code_chunk = CodeChunk(
                        file_id=code_file.id,
                        chunk_index=chunk_data.chunk_index,
                        content=chunk_data.content,
                        start_line=chunk_data.start_line,
                        end_line=chunk_data.end_line,
                        embedding=chunk_embedding,
                    )
                    db.add(code_chunk)
                    total_chunks += 1

            # Commit the entire batch atomically
            await db.commit()
            logger.info(
                "Successfully indexed repository %s: %d files, %d chunks",
                repository_id,
                total_files,
                total_chunks,
            )

        except Exception as exc:
            await db.rollback()
            logger.exception("Failed to commit indexing data for repository %s: %s", repository_id, exc)
            raise IndexingError("Failed to store indexing data in the database.") from exc

        return IndexingResult(
            repository_id=repository_id,
            files_indexed=total_files,
            chunks_created=total_chunks,
        )
