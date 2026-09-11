"""
Repository ingestion coordinator service.
"""

from datetime import datetime, timezone
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.repository import IngestionStatus, Repository
from app.services.repository_cloner import GitCloneError, RepositoryCloner
from app.services.repository_files import DiscoveredFile, discover_repository_files
from app.services.repository_url import (
    InvalidRepositoryURLError,
    validate_and_normalize_github_url,
)

logger = logging.getLogger(__name__)


class RepositoryAlreadyExistsError(ValueError):
    """Raised when attempting to ingest a repository URL that has already been registered."""
    pass


class RepositoryIngestionService:
    """Orchestrates validation, database persistence, cloning, and file discovery."""

    def __init__(self, cloner: RepositoryCloner | None = None) -> None:
        storage_root = Path(settings.repository_storage_path)
        self.cloner = cloner or RepositoryCloner(
            storage_root=storage_root,
            timeout_seconds=settings.git_clone_timeout,
        )

    async def ingest(
        self,
        raw_url: str,
        db: AsyncSession,
    ) -> tuple[Repository, list[DiscoveredFile]]:
        """Execute the complete repository ingestion lifecycle.

        Flow:
          1. Validate and normalize GitHub URL (raises on invalid format)
          2. Check for duplicate repository in database (raises 409 Conflict if found)
          3. Create Repository record with status = PENDING
          4. Update status = PROCESSING
          5. Clone repository locally via system git
          6. Discover and filter source files
          7. On success: status = COMPLETED, ingested_at = now()
          8. On failure: status = FAILED, error_message = safe description
        """
        # Step 1: Validate GitHub URL
        normalized_url, repo_name = validate_and_normalize_github_url(raw_url)

        # Step 2: Check for existing record
        query = select(Repository).where(Repository.url == normalized_url)
        result = await db.execute(query)
        existing = result.scalar_one_or_none()
        if existing is not None:
            raise RepositoryAlreadyExistsError(
                f"Repository '{normalized_url}' is already registered (id: {existing.id})."
            )

        # Step 3: Create initial record with PENDING status
        repo = Repository(
            url=normalized_url,
            name=repo_name,
            status=IngestionStatus.PENDING,
        )
        db.add(repo)
        await db.commit()
        await db.refresh(repo)
        logger.info("Created repository record %s in PENDING state", repo.id)

        # Step 4: Transition to PROCESSING
        repo.status = IngestionStatus.PROCESSING
        await db.commit()
        await db.refresh(repo)
        logger.info("Repository %s moved to PROCESSING state", repo.id)

        discovered_files: list[DiscoveredFile] = []
        try:
            # Step 5: Clone repository
            target_dir = await self.cloner.clone(normalized_url, repo.id)

            # Step 6: Discover & filter files
            discovered_files = discover_repository_files(target_dir)
            logger.info("Discovered %d relevant files for repository %s", len(discovered_files), repo.id)

            # Step 7: Update to COMPLETED
            repo.status = IngestionStatus.COMPLETED
            repo.ingested_at = datetime.now(timezone.utc)
            repo.error_message = None
            await db.commit()
            await db.refresh(repo)
            logger.info("Repository %s ingestion COMPLETED successfully", repo.id)

            return repo, discovered_files

        except GitCloneError as clone_err:
            logger.warning("Repository %s ingestion failed during cloning: %s", repo.id, clone_err)
            repo.status = IngestionStatus.FAILED
            repo.error_message = str(clone_err)
            await db.commit()
            await db.refresh(repo)
            return repo, []

        except Exception as exc:
            logger.exception("Unexpected failure during ingestion of repository %s: %s", repo.id, exc)
            self.cloner.cleanup(repo.id)
            repo.status = IngestionStatus.FAILED
            repo.error_message = "An unexpected error occurred during repository ingestion."
            await db.commit()
            await db.refresh(repo)
            return repo, []
