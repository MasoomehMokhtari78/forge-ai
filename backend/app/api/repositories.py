"""
API router for repository management and ingestion.
"""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository
from app.schemas.indexing import IndexingResponse, IndexSummaryResponse
from app.schemas.repository import RepositoryCreate, RepositoryResponse
from app.services.repository_indexing import (
    IndexingError,
    RepositoryFilesNotAvailableError,
    RepositoryNotFoundError,
    RepositoryNotReadyForIndexingError,
    RepositoryIndexingService,
)
from app.services.repository_ingestion import (
    RepositoryAlreadyExistsError,
    RepositoryIngestionService,
)
from app.services.repository_url import InvalidRepositoryURLError

router = APIRouter(prefix="/repositories", tags=["repositories"])


# Dependency to provide the ingestion service
def get_ingestion_service() -> RepositoryIngestionService:
    return RepositoryIngestionService()


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a public GitHub repository",
    description="Validates the URL, creates a repository record, clones it locally, and discovers source files.",
)
async def ingest_repository(
    payload: RepositoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RepositoryIngestionService, Depends(get_ingestion_service)],
) -> Repository:
    try:
        repo, _discovered_files = await service.ingest(raw_url=payload.url, db=db)
        return repo
    except InvalidRepositoryURLError as err:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(err),
        ) from err
    except RepositoryAlreadyExistsError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err


@router.get(
    "/{repository_id}",
    response_model=RepositoryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get repository details by ID",
)
async def get_repository(
    repository_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Repository:
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository with ID '{repository_id}' not found.",
        )
    return repo


@router.get(
    "",
    response_model=list[RepositoryResponse],
    status_code=status.HTTP_200_OK,
    summary="List all ingested repositories",
)
async def list_repositories(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[Repository]:
    query = select(Repository).order_by(Repository.created_at.desc())
    result = await db.execute(query)
    return list(result.scalars().all())


# ===========================================================================
# Indexing Endpoints
# ===========================================================================

def get_indexing_service() -> RepositoryIndexingService:
    return RepositoryIndexingService()


@router.post(
    "/{repository_id}/index",
    response_model=IndexingResponse,
    status_code=status.HTTP_200_OK,
    summary="Index source code chunks and generate vector embeddings",
    description="Discovers eligible repository files, chunks content, generates embeddings, and persists to pgvector.",
)
async def index_repository(
    repository_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RepositoryIndexingService, Depends(get_indexing_service)],
) -> IndexingResponse:
    try:
        result = await service.index_repository(repository_id=repository_id, db=db)
        return IndexingResponse(
            repository_id=result.repository_id,
            status="completed",
            files_indexed=result.files_indexed,
            chunks_created=result.chunks_created,
        )
    except RepositoryNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except RepositoryNotReadyForIndexingError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except RepositoryFilesNotAvailableError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err
    except IndexingError as err:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(err),
        ) from err


@router.get(
    "/{repository_id}/index",
    response_model=IndexSummaryResponse,
    status_code=status.HTTP_200_OK,
    summary="Get repository indexing metrics",
    description="Returns the total number of indexed files and chunks currently stored for the repository.",
)
async def get_repository_index_summary(
    repository_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IndexSummaryResponse:
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository with ID '{repository_id}' not found.",
        )

    # Count indexed files
    files_query = select(func.count()).select_from(CodeFile).where(CodeFile.repository_id == repository_id)
    files_res = await db.execute(files_query)
    files_count = files_res.scalar_one()

    # Count indexed chunks
    chunks_query = (
        select(func.count())
        .select_from(CodeChunk)
        .join(CodeFile, CodeChunk.file_id == CodeFile.id)
        .where(CodeFile.repository_id == repository_id)
    )
    chunks_res = await db.execute(chunks_query)
    chunks_count = chunks_res.scalar_one()

    return IndexSummaryResponse(
        repository_id=repository_id,
        files_indexed=files_count,
        chunks_created=chunks_count,
    )

