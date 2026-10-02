"""
API router for engineering knowledge management and document ingestion.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.schemas.knowledge import (
    KnowledgeCreate,
    KnowledgeDocumentResponse,
    KnowledgeResponse,
)
from app.services.engineering_knowledge import (
    DocumentAccessDeniedError,
    DocumentAlreadyExistsError,
    DocumentNotFoundError,
    EngineeringKnowledgeService,
    KnowledgeAlreadyExistsError,
    KnowledgeNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def get_knowledge_service() -> EngineeringKnowledgeService:
    """Dependency injection factory for EngineeringKnowledgeService."""
    return EngineeringKnowledgeService()


async def build_document_response(
    doc: KnowledgeDocument,
    db: AsyncSession,
) -> KnowledgeDocumentResponse:
    """Build a KnowledgeDocumentResponse including chunk count."""
    count_stmt = select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.document_id == doc.id)
    count_res = await db.execute(count_stmt)
    chunks_count = count_res.scalar_one() or 0

    return KnowledgeDocumentResponse(
        id=doc.id,
        knowledge_id=doc.knowledge_id,
        filename=doc.filename,
        source_type=doc.source_type,
        file_size_bytes=doc.file_size_bytes,
        status=doc.status,
        error_message=doc.error_message,
        chunks_count=chunks_count,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


async def build_knowledge_response(
    knowledge: EngineeringKnowledge,
    db: AsyncSession,
) -> KnowledgeResponse:
    """Build a KnowledgeResponse including its documents with chunk counts."""
    # Fetch documents for this knowledge scope
    docs_stmt = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.knowledge_id == knowledge.id)
        .order_by(KnowledgeDocument.created_at.asc())
    )
    docs_res = await db.execute(docs_stmt)
    docs = docs_res.scalars().all()

    doc_responses = [await build_document_response(doc, db) for doc in docs]

    return KnowledgeResponse(
        id=knowledge.id,
        name=knowledge.name,
        description=knowledge.description,
        status=knowledge.status,
        error_message=knowledge.error_message,
        created_at=knowledge.created_at,
        updated_at=knowledge.updated_at,
        documents=doc_responses,
    )


@router.post(
    "",
    response_model=KnowledgeResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new engineering knowledge scope",
    description="Registers a new user-defined engineering knowledge scope (e.g. 'Design Pattern Guidance').",
)
async def create_knowledge(
    payload: KnowledgeCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[EngineeringKnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeResponse:
    try:
        knowledge = await service.create_knowledge(
            name=payload.name,
            description=payload.description,
            db=db,
        )
        return await build_knowledge_response(knowledge, db)
    except KnowledgeAlreadyExistsError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err


@router.get(
    "",
    response_model=list[KnowledgeResponse],
    status_code=status.HTTP_200_OK,
    summary="List all engineering knowledge scopes",
)
async def list_knowledge(
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[EngineeringKnowledgeService, Depends(get_knowledge_service)],
) -> list[KnowledgeResponse]:
    scopes = await service.list_knowledge(db=db)
    return [await build_knowledge_response(scope, db) for scope in scopes]


@router.get(
    "/{knowledge_id}",
    response_model=KnowledgeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get engineering knowledge scope by ID",
)
async def get_knowledge(
    knowledge_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[EngineeringKnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeResponse:
    scope = await service.get_knowledge(knowledge_id=knowledge_id, db=db)
    if scope is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Engineering knowledge scope '{knowledge_id}' not found.",
        )
    return await build_knowledge_response(scope, db)


@router.delete(
    "/{knowledge_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an engineering knowledge scope",
    description="Deletes the knowledge scope and cascade deletes all documents and vector chunks.",
)
async def delete_knowledge(
    knowledge_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[EngineeringKnowledgeService, Depends(get_knowledge_service)],
) -> None:
    try:
        await service.delete_knowledge(knowledge_id=knowledge_id, db=db)
    except KnowledgeNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err


@router.post(
    "/{knowledge_id}/documents",
    response_model=KnowledgeDocumentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload and ingest a PDF document into a knowledge scope",
    description="Uploads a PDF, extracts text, chunks content, generates embeddings, and persists chunks.",
)
async def upload_document(
    knowledge_id: UUID,
    file: Annotated[UploadFile, File(description="PDF document file")],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[EngineeringKnowledgeService, Depends(get_knowledge_service)],
) -> KnowledgeDocumentResponse:
    # Validate file extension
    filename = file.filename or "document.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF documents are supported (.pdf).",
        )

    # Read content
    try:
        content = await file.read()
    except Exception as exc:
        logger.warning("Failed to read uploaded file %s: %s", filename, exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read uploaded file: {exc}",
        ) from exc

    if len(content) > settings.max_file_size_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File size ({len(content)} bytes) exceeds the maximum allowed limit "
                f"of {settings.max_file_size_bytes} bytes."
            ),
        )

    try:
        doc = await service.ingest_document(
            knowledge_id=knowledge_id,
            filename=filename,
            content=content,
            db=db,
        )
        return await build_document_response(doc, db)
    except KnowledgeNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except DocumentAlreadyExistsError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        ) from err


@router.get(
    "/{knowledge_id}/documents",
    response_model=list[KnowledgeDocumentResponse],
    status_code=status.HTTP_200_OK,
    summary="List all documents in an engineering knowledge scope",
)
async def list_documents(
    knowledge_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[EngineeringKnowledgeService, Depends(get_knowledge_service)],
) -> list[KnowledgeDocumentResponse]:
    try:
        docs = await service.list_documents(knowledge_id=knowledge_id, db=db)
        return [await build_document_response(doc, db) for doc in docs]
    except KnowledgeNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err


@router.delete(
    "/{knowledge_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a document from an engineering knowledge scope",
)
async def delete_document(
    knowledge_id: UUID,
    document_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[EngineeringKnowledgeService, Depends(get_knowledge_service)],
) -> None:
    try:
        await service.delete_document(
            knowledge_id=knowledge_id,
            document_id=document_id,
            db=db,
        )
    except DocumentNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except DocumentAccessDeniedError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
    except KnowledgeNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        ) from err
