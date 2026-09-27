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
from app.schemas.agent import AgentRequest, AgentResponse
from app.schemas.indexing import IndexingResponse, IndexSummaryResponse
from app.schemas.rag import (
    ChatRequest,
    ChatResponse,
    SearchRequest,
    SearchResponse,
)
from app.core.config import settings
from app.schemas.repository import (
    FileContentResponse,
    FileMetadata,
    RepositoryCreate,
    RepositoryFilesResponse,
    RepositoryResponse,
)
from app.services.repository_files import discover_repository_files
from app.services.agent import AgentService, get_default_agent_service
from app.services.rag import RAGService, get_default_rag_service
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
from app.services.retrieval import (
    RepositoryNotFoundError as RetrievalRepoNotFoundError,
    RepositoryNotReadyForSearchError,
    RetrievalService,
)

router = APIRouter(prefix="/repositories", tags=["repositories"])


import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from app.models.repository import IngestionStatus, Repository

# Dependency to provide the ingestion service
def get_ingestion_service() -> RepositoryIngestionService:
    return RepositoryIngestionService()


def get_indexing_service() -> RepositoryIndexingService:
    return RepositoryIndexingService()


@router.post(
    "",
    response_model=RepositoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a public GitHub repository",
    description="Validates the URL, creates a repository record, clones it locally, discovers source files, and automatically indexes chunks/embeddings.",
)
async def ingest_repository(
    payload: RepositoryCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RepositoryIngestionService, Depends(get_ingestion_service)],
    indexing_service: Annotated[RepositoryIndexingService, Depends(get_indexing_service)],
) -> Repository:
    try:
        repo, _discovered_files = await service.ingest(raw_url=payload.url, db=db)
        if payload.auto_index and repo.status == IngestionStatus.COMPLETED:
            try:
                storage_root = getattr(service.cloner, "storage_root", None)
                if storage_root is not None:
                    indexing_service.storage_root = Path(storage_root).resolve()
                await indexing_service.index_repository(repository_id=repo.id, db=db)
                logger.info("Automatic indexing completed for repository %s", repo.id)
            except Exception as idx_err:
                logger.warning("Automatic indexing for repository %s deferred or failed: %s", repo.id, idx_err)
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


@router.delete(
    "/{repository_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a repository",
    description="Deletes repository metadata, cascade-deletes indexed files, chunks, and cleans up local storage.",
)
async def delete_repository(
    repository_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RepositoryIngestionService, Depends(get_ingestion_service)],
) -> None:
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository with ID '{repository_id}' not found.",
        )
    service.cloner.cleanup(repository_id)
    await db.delete(repo)
    await db.commit()


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
# File Explorer Endpoints
# ===========================================================================


@router.get(
    "/{repository_id}/files",
    response_model=RepositoryFilesResponse,
    status_code=status.HTTP_200_OK,
    summary="List repository files",
    description="Returns list of files with relative path, extension, and size in bytes.",
)
async def list_repository_files(
    repository_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RepositoryFilesResponse:
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository with ID '{repository_id}' not found.",
        )

    # 1. First check if files are stored in PostgreSQL CodeFile table
    query = (
        select(CodeFile)
        .where(CodeFile.repository_id == repository_id)
        .order_by(CodeFile.path.asc())
    )
    result = await db.execute(query)
    code_files = list(result.scalars().all())
    if code_files:
        return RepositoryFilesResponse(
            repository_id=repository_id,
            total_files=len(code_files),
            files=[
                FileMetadata(
                    path=f.path,
                    size_bytes=f.size_bytes,
                    extension=f.extension,
                )
                for f in code_files
            ],
        )

    # 2. If not in DB, discover files from the cloned local repository
    repo_dir = (Path(settings.repository_storage_path) / str(repository_id)).resolve()
    if not repo_dir.exists() or not repo_dir.is_dir():
        return RepositoryFilesResponse(
            repository_id=repository_id,
            total_files=0,
            files=[],
        )

    discovered = discover_repository_files(
        repo_dir,
        max_file_size_bytes=settings.max_file_size_bytes,
    )
    return RepositoryFilesResponse(
        repository_id=repository_id,
        total_files=len(discovered),
        files=[
            FileMetadata(
                path=f.relative_path,
                size_bytes=f.size_bytes,
                extension=f.extension,
            )
            for f in discovered
        ],
    )


@router.get(
    "/{repository_id}/files/{file_path:path}",
    response_model=FileContentResponse,
    status_code=status.HTTP_200_OK,
    summary="Read content of a repository file",
    description="Reads and returns text content, line count, and size for a specific repository file.",
)
async def read_repository_file(
    repository_id: UUID,
    file_path: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileContentResponse:
    repo = await db.get(Repository, repository_id)
    if repo is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Repository with ID '{repository_id}' not found.",
        )

    clean_path = file_path.strip()
    if not clean_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File path must not be empty.",
        )

    raw_path_obj = Path(clean_path)

    # Reject absolute paths or Windows drive letters
    if clean_path.startswith(("/", "\\")) or raw_path_obj.is_absolute() or raw_path_obj.drive:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Absolute paths are forbidden: '{clean_path}'",
        )

    # Reject directory traversal
    if any(part in ("..", "~") for part in raw_path_obj.parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Directory traversal detected in path: '{clean_path}'",
        )

    repo_root = (Path(settings.repository_storage_path) / str(repository_id)).resolve()
    if not repo_root.exists() or not repo_root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cloned repository files are not available on server.",
        )

    target_file = (repo_root / clean_path).resolve()

    if not target_file.is_relative_to(repo_root):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path escapes repository root: '{clean_path}'",
        )

    if not target_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: '{clean_path}'",
        )

    if not target_file.is_file():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Path is not a regular file: '{clean_path}'",
        )

    file_size = target_file.stat().st_size
    if file_size > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File '{clean_path}' exceeds maximum allowable size of {settings.max_file_size_bytes} bytes.",
        )

    try:
        content = target_file.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read file '{clean_path}': {exc}",
        ) from exc

    lines = content.splitlines()
    rel_posix_path = target_file.relative_to(repo_root).as_posix()

    return FileContentResponse(
        repository_id=repository_id,
        path=rel_posix_path,
        total_lines=len(lines),
        size_bytes=file_size,
        content=content,
    )


# ===========================================================================
# Indexing Endpoints
# ===========================================================================


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


# ===========================================================================
# Retrieval & RAG Endpoints
# ===========================================================================

def get_retrieval_service() -> RetrievalService:
    return RetrievalService()


def get_rag_service() -> RAGService:
    return get_default_rag_service()


@router.post(
    "/{repository_id}/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Semantic code search within a repository",
    description="Performs pgvector cosine similarity search to retrieve relevant code chunks with repository isolation.",
)
async def search_repository(
    repository_id: UUID,
    payload: SearchRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> SearchResponse:
    try:
        results = await service.search(
            repository_id=repository_id,
            query=payload.query,
            db=db,
            top_k=payload.top_k,
            similarity_threshold=payload.similarity_threshold,
        )
        return SearchResponse(
            repository_id=repository_id,
            query=payload.query,
            results=results,
        )
    except RetrievalRepoNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except RepositoryNotReadyForSearchError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err


@router.post(
    "/{repository_id}/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Ask questions about repository code (RAG)",
    description="Retrieves relevant code chunks, packs budgeted context, and generates an answer with authoritative citations.",
)
async def chat_repository(
    repository_id: UUID,
    payload: ChatRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[RAGService, Depends(get_rag_service)],
) -> ChatResponse:
    try:
        return await service.answer_question(
            repository_id=repository_id,
            question=payload.question,
            db=db,
        )
    except RetrievalRepoNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except RepositoryNotReadyForSearchError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err


# ===========================================================================
# Agent Endpoint
# ===========================================================================

def get_agent_service() -> AgentService:
    return get_default_agent_service()


@router.post(
    "/{repository_id}/agent",
    response_model=AgentResponse,
    status_code=status.HTTP_200_OK,
    summary="Investigate repository code with bounded read-only agent",
    description="Iteratively uses read-only tools (search, read file, list files) to investigate a question and formulate an answer with authoritative citations.",
)
async def run_agent(
    repository_id: UUID,
    payload: AgentRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[AgentService, Depends(get_agent_service)],
) -> AgentResponse:
    try:
        return await service.run(
            repository_id=repository_id,
            question=payload.question,
            db=db,
            max_iterations=payload.max_iterations,
        )
    except RetrievalRepoNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except RepositoryNotReadyForSearchError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        ) from err



