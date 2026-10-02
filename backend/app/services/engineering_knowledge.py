"""
Engineering Knowledge service managing knowledge scopes, document ingestion, and chunk persistence.
"""

from collections.abc import Sequence
import logging
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.chunking import KnowledgeChunkData, chunk_knowledge_document
from app.services.embedding import (
    EmbeddingError,
    EmbeddingService,
    get_default_embedding_service,
)
from app.services.pdf_extraction import PDFExtractionError, extract_text_from_pdf

logger = logging.getLogger(__name__)


class KnowledgeError(Exception):
    """Base exception for knowledge domain operations."""
    pass


class KnowledgeNotFoundError(KnowledgeError):
    """Raised when an engineering knowledge scope does not exist."""
    pass


class KnowledgeAlreadyExistsError(KnowledgeError):
    """Raised when an engineering knowledge scope name already exists."""
    pass


class DocumentNotFoundError(KnowledgeError):
    """Raised when a knowledge document does not exist."""
    pass


class DocumentAccessDeniedError(KnowledgeError):
    """Raised when attempting to access a document through an unassociated knowledge scope."""
    pass


class DocumentAlreadyExistsError(KnowledgeError):
    """Raised when a document with the same filename already exists in the knowledge scope."""
    pass


class EngineeringKnowledgeService:
    """Coordinates engineering knowledge scopes, document ingestion, and chunk persistence."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.embedding_service = embedding_service or get_default_embedding_service()

    async def create_knowledge(
        self,
        name: str,
        description: str | None,
        db: AsyncSession,
    ) -> EngineeringKnowledge:
        """Create a new engineering knowledge scope.

        Raises:
            KnowledgeAlreadyExistsError: If a scope with the given name already exists.
        """
        normalized_name = name.strip()
        existing_stmt = select(EngineeringKnowledge).where(
            EngineeringKnowledge.name == normalized_name
        )
        existing_res = await db.execute(existing_stmt)
        if existing_res.scalar_one_or_none() is not None:
            raise KnowledgeAlreadyExistsError(
                f"Engineering knowledge scope '{normalized_name}' already exists."
            )

        knowledge = EngineeringKnowledge(
            name=normalized_name,
            description=description.strip() if description else None,
            status=KnowledgeStatus.PENDING,
        )
        db.add(knowledge)
        await db.commit()
        await db.refresh(knowledge)
        logger.info("Created engineering knowledge scope '%s' (%s)", knowledge.name, knowledge.id)
        return knowledge

    async def get_knowledge(
        self,
        knowledge_id: UUID,
        db: AsyncSession,
    ) -> EngineeringKnowledge | None:
        """Retrieve an engineering knowledge scope by ID, including its documents."""
        stmt = (
            select(EngineeringKnowledge)
            .where(EngineeringKnowledge.id == knowledge_id)
            .options(selectinload(EngineeringKnowledge.documents))
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    async def list_knowledge(
        self,
        db: AsyncSession,
    ) -> Sequence[EngineeringKnowledge]:
        """List all engineering knowledge scopes ordered by creation time."""
        stmt = (
            select(EngineeringKnowledge)
            .options(selectinload(EngineeringKnowledge.documents))
            .order_by(EngineeringKnowledge.created_at.desc())
        )
        res = await db.execute(stmt)
        return res.scalars().all()

    async def delete_knowledge(
        self,
        knowledge_id: UUID,
        db: AsyncSession,
    ) -> bool:
        """Delete an engineering knowledge scope and cascade all documents and chunks.

        Raises:
            KnowledgeNotFoundError: If the knowledge scope does not exist.
        """
        knowledge = await db.get(EngineeringKnowledge, knowledge_id)
        if knowledge is None:
            raise KnowledgeNotFoundError(
                f"Engineering knowledge scope '{knowledge_id}' not found."
            )

        await db.delete(knowledge)
        await db.commit()
        logger.info("Deleted engineering knowledge scope %s and cascaded records", knowledge_id)
        return True

    async def ingest_document(
        self,
        knowledge_id: UUID,
        filename: str,
        content: bytes,
        db: AsyncSession,
    ) -> KnowledgeDocument:
        """Ingest a PDF document into an engineering knowledge scope.

        Executes:
          1. Scope existence verification
          2. Filename duplicate check
          3. KnowledgeDocument record creation (PENDING -> PROCESSING)
          4. PDF text extraction & validation
          5. Knowledge chunking preserving page metadata
          6. Vector embedding generation via EmbeddingService
          7. Atomic persistence of KnowledgeChunk records
          8. Status transition to COMPLETED (or FAILED with error_message)
        """
        knowledge = await db.get(EngineeringKnowledge, knowledge_id)
        if knowledge is None:
            raise KnowledgeNotFoundError(
                f"Engineering knowledge scope '{knowledge_id}' not found."
            )

        clean_filename = filename.strip()
        existing_doc_stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.knowledge_id == knowledge_id,
            KnowledgeDocument.filename == clean_filename,
        )
        existing_doc_res = await db.execute(existing_doc_stmt)
        if existing_doc_res.scalar_one_or_none() is not None:
            raise DocumentAlreadyExistsError(
                f"Document '{clean_filename}' already exists in knowledge scope '{knowledge.name}'."
            )

        doc = KnowledgeDocument(
            knowledge_id=knowledge_id,
            filename=clean_filename,
            source_type="pdf",
            file_size_bytes=len(content),
            status=KnowledgeStatus.PENDING,
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)

        # Transition to PROCESSING
        doc.status = KnowledgeStatus.PROCESSING
        if knowledge.status == KnowledgeStatus.PENDING:
            knowledge.status = KnowledgeStatus.PROCESSING
        await db.commit()
        await db.refresh(doc)

        # Step 4: Extract text from PDF
        try:
            extracted_pages = extract_text_from_pdf(content)
        except PDFExtractionError as pdf_err:
            logger.warning("PDF extraction failed for document %s: %s", doc.id, pdf_err)
            doc.status = KnowledgeStatus.FAILED
            doc.error_message = str(pdf_err)
            await db.commit()
            await db.refresh(doc)
            return doc
        except Exception as exc:
            logger.exception("Unexpected error during PDF extraction for %s: %s", doc.id, exc)
            doc.status = KnowledgeStatus.FAILED
            doc.error_message = f"Unexpected error during PDF extraction: {exc}"
            await db.commit()
            await db.refresh(doc)
            return doc

        # Step 5: Chunk text
        chunks_data: list[KnowledgeChunkData] = chunk_knowledge_document(extracted_pages)
        if not chunks_data:
            doc.status = KnowledgeStatus.FAILED
            doc.error_message = "No usable text chunks could be produced from document."
            await db.commit()
            await db.refresh(doc)
            return doc

        # Step 6: Generate vector embeddings
        chunk_texts = [c.content for c in chunks_data]
        all_embeddings: list[list[float]] = []
        batch_size = 64
        try:
            for i in range(0, len(chunk_texts), batch_size):
                batch = chunk_texts[i : i + batch_size]
                batch_embeddings = await self.embedding_service.get_embeddings(batch)
                all_embeddings.extend(batch_embeddings)
        except EmbeddingError as emb_err:
            logger.error("Embedding generation failed for document %s: %s", doc.id, emb_err)
            doc.status = KnowledgeStatus.FAILED
            doc.error_message = f"Embedding generation failed: {emb_err}"
            await db.commit()
            await db.refresh(doc)
            return doc
        except Exception as exc:
            logger.exception("Unexpected error during embedding generation for %s: %s", doc.id, exc)
            doc.status = KnowledgeStatus.FAILED
            doc.error_message = "Unexpected error during embedding generation."
            await db.commit()
            await db.refresh(doc)
            return doc

        # Step 7: Atomic persistence of KnowledgeChunk records
        try:
            for chunk_data, emb in zip(chunks_data, all_embeddings, strict=True):
                chunk_record = KnowledgeChunk(
                    knowledge_id=knowledge_id,
                    document_id=doc.id,
                    chunk_index=chunk_data.chunk_index,
                    content=chunk_data.content,
                    page_number=chunk_data.page_number,
                    embedding=emb,
                )
                db.add(chunk_record)

            doc.status = KnowledgeStatus.COMPLETED
            doc.error_message = None
            knowledge.status = KnowledgeStatus.COMPLETED
            await db.commit()
            await db.refresh(doc)
            logger.info(
                "Successfully ingested document %s (%s): %d chunks created",
                doc.filename,
                doc.id,
                len(chunks_data),
            )
            return doc
        except Exception as exc:
            await db.rollback()
            logger.exception("Database error persisting chunks for document %s: %s", doc.id, exc)
            doc.status = KnowledgeStatus.FAILED
            doc.error_message = "Failed to store knowledge chunks in database."
            await db.commit()
            await db.refresh(doc)
            return doc

    async def list_documents(
        self,
        knowledge_id: UUID,
        db: AsyncSession,
    ) -> Sequence[KnowledgeDocument]:
        """List all documents belonging to a knowledge scope."""
        knowledge = await db.get(EngineeringKnowledge, knowledge_id)
        if knowledge is None:
            raise KnowledgeNotFoundError(
                f"Engineering knowledge scope '{knowledge_id}' not found."
            )

        stmt = (
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_id == knowledge_id)
            .order_by(KnowledgeDocument.created_at.asc())
        )
        res = await db.execute(stmt)
        return res.scalars().all()

    async def get_document(
        self,
        knowledge_id: UUID,
        document_id: UUID,
        db: AsyncSession,
    ) -> KnowledgeDocument:
        """Retrieve a specific document verifying knowledge scope ownership.

        Raises:
            DocumentNotFoundError: If the document does not exist.
            DocumentAccessDeniedError: If the document belongs to a different knowledge scope.
        """
        doc = await db.get(KnowledgeDocument, document_id)
        if doc is None:
            raise DocumentNotFoundError(f"Knowledge document '{document_id}' not found.")

        if doc.knowledge_id != knowledge_id:
            logger.warning(
                "Security violation: document %s belongs to scope %s, requested scope %s",
                document_id,
                doc.knowledge_id,
                knowledge_id,
            )
            raise DocumentAccessDeniedError(
                "Document does not belong to the specified knowledge scope."
            )

        return doc

    async def delete_document(
        self,
        knowledge_id: UUID,
        document_id: UUID,
        db: AsyncSession,
    ) -> bool:
        """Delete a document verifying scope ownership, cascading chunks.

        Raises:
            DocumentNotFoundError: If the document does not exist.
            DocumentAccessDeniedError: If the document belongs to a different knowledge scope.
        """
        doc = await self.get_document(knowledge_id=knowledge_id, document_id=document_id, db=db)
        await db.delete(doc)

        # Check if there are other completed documents in this scope
        remaining_stmt = select(KnowledgeDocument).where(
            KnowledgeDocument.knowledge_id == knowledge_id,
            KnowledgeDocument.id != document_id,
            KnowledgeDocument.status == KnowledgeStatus.COMPLETED,
        )
        remaining_res = await db.execute(remaining_stmt)
        has_completed = remaining_res.scalars().first() is not None

        knowledge = await db.get(EngineeringKnowledge, knowledge_id)
        if knowledge is not None:
            if not has_completed:
                knowledge.status = KnowledgeStatus.PENDING

        await db.commit()
        logger.info("Deleted document %s from knowledge scope %s", document_id, knowledge_id)
        return True
