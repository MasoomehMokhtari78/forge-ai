"""
Tests for PDF text extraction, knowledge chunking, and document ingestion pipeline.
"""

from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.chunking import chunk_knowledge_document
from app.services.embedding import EmbeddingError, MockEmbeddingService
from app.services.engineering_knowledge import EngineeringKnowledgeService
from app.services.pdf_extraction import (
    ExtractedPage,
    PDFExtractionError,
    extract_text_from_pdf,
)
from tests.pdf_helpers import generate_scanned_blank_pdf, generate_test_pdf


def test_pdf_text_extraction_success():
    """Verify that text is correctly extracted page-by-page from a valid PDF."""
    pages = [
        "Page 1: Factory Pattern encapsulates object instantiation.",
        "Page 2: Observer Pattern defines a one-to-many dependency between objects.",
    ]
    pdf_bytes = generate_test_pdf(pages)
    extracted = extract_text_from_pdf(pdf_bytes)

    assert len(extracted) == 2
    assert extracted[0].page_number == 1
    assert "Factory Pattern" in extracted[0].text
    assert extracted[1].page_number == 2
    assert "Observer Pattern" in extracted[1].text


def test_pdf_extraction_scanned_pdf_fails_gracefully():
    """Verify that a PDF without usable text raises an informative OCR-related error."""
    scanned_bytes = generate_scanned_blank_pdf(num_pages=2)

    with pytest.raises(PDFExtractionError) as exc_info:
        extract_text_from_pdf(scanned_bytes)

    assert "Text could not be extracted from this PDF" in str(exc_info.value)
    assert "scanned/image-based and may require OCR" in str(exc_info.value)


def test_pdf_extraction_corrupted_bytes_fails():
    """Verify that corrupted binary data raises PDFExtractionError."""
    with pytest.raises(PDFExtractionError) as exc_info:
        extract_text_from_pdf(b"not a valid pdf content at all")

    assert "Invalid or corrupted PDF file" in str(exc_info.value)


def test_pdf_extraction_empty_bytes_fails():
    """Verify that 0-byte input raises PDFExtractionError."""
    with pytest.raises(PDFExtractionError) as exc_info:
        extract_text_from_pdf(b"")

    assert "empty (0 bytes)" in str(exc_info.value)


def test_knowledge_chunking_preserves_page_metadata():
    """Verify chunking maintains accurate page numbers and monotonic chunk indices."""
    pages = [
        ExtractedPage(page_number=1, text="Introduction to Design Patterns in Python."),
        ExtractedPage(page_number=2, text="Detailed discussion of Singleton and Factory Method patterns."),
    ]
    chunks = chunk_knowledge_document(pages, max_chunk_chars=500, overlap_chars=50)

    assert len(chunks) == 2
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert "Introduction" in chunks[0].content

    assert chunks[1].chunk_index == 1
    assert chunks[1].page_number == 2
    assert "Singleton" in chunks[1].content


def test_knowledge_chunking_long_page_splits_with_overlap():
    """Verify that a page exceeding max_chunk_chars is split into multiple overlapping chunks."""
    long_text = "Word " * 200  # 1000 characters
    pages = [ExtractedPage(page_number=3, text=long_text)]
    chunks = chunk_knowledge_document(pages, max_chunk_chars=300, overlap_chars=50)

    assert len(chunks) > 1
    for c in chunks:
        assert c.page_number == 3
        assert len(c.content) <= 300
    # Check monotonic index
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


async def test_ingest_document_success(db_session):
    """Verify the full document ingestion pipeline: extraction, chunking, embedding, persistence."""
    knowledge = EngineeringKnowledge(name="GoF Design Patterns")
    db_session.add(knowledge)
    await db_session.flush()

    pdf_bytes = generate_test_pdf([
        "Page 1: Strategy pattern defines a family of algorithms and makes them interchangeable.",
        "Page 2: Adapter pattern converts the interface of a class into another interface.",
    ])

    service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())
    doc = await service.ingest_document(
        knowledge_id=knowledge.id,
        filename="patterns.pdf",
        content=pdf_bytes,
        db=db_session,
    )

    assert doc.id is not None
    assert doc.status == KnowledgeStatus.COMPLETED
    assert doc.error_message is None
    assert doc.file_size_bytes == len(pdf_bytes)

    # Verify chunks in database
    chunks_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id).order_by(KnowledgeChunk.chunk_index)
    chunks_res = await db_session.execute(chunks_stmt)
    chunks = chunks_res.scalars().all()

    assert len(chunks) == 2
    assert chunks[0].page_number == 1
    assert "Strategy pattern" in chunks[0].content
    assert chunks[1].page_number == 2
    assert "Adapter pattern" in chunks[1].content
    assert len(chunks[0].embedding) == 384


async def test_ingest_document_scanned_pdf_records_failed_status(db_session):
    """Verify that uploading a scanned PDF marks document as FAILED and records the error message."""
    knowledge = EngineeringKnowledge(name="Scanned Scope")
    db_session.add(knowledge)
    await db_session.flush()

    scanned_pdf = generate_scanned_blank_pdf(num_pages=1)
    service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())

    doc = await service.ingest_document(
        knowledge_id=knowledge.id,
        filename="scanned.pdf",
        content=scanned_pdf,
        db=db_session,
    )

    assert doc.id is not None
    assert doc.status == KnowledgeStatus.FAILED
    assert doc.error_message is not None
    assert "scanned/image-based and may require OCR" in doc.error_message

    # Verify no chunks were stored for failed document
    chunks_stmt = select(KnowledgeChunk).where(KnowledgeChunk.document_id == doc.id)
    chunks_res = await db_session.execute(chunks_stmt)
    assert chunks_res.scalars().first() is None


async def test_ingest_document_embedding_failure_records_failed(db_session):
    """Verify that an unexpected failure in embedding generation marks the document as FAILED."""
    knowledge = EngineeringKnowledge(name="Embedding Failure Scope")
    db_session.add(knowledge)
    await db_session.flush()

    pdf_bytes = generate_test_pdf(["Page 1: Some engineering content that will fail during embedding."])

    mock_emb = MockEmbeddingService()
    mock_emb.get_embeddings = AsyncMock(side_effect=EmbeddingError("Simulated embedding service failure"))

    service = EngineeringKnowledgeService(embedding_service=mock_emb)
    doc = await service.ingest_document(
        knowledge_id=knowledge.id,
        filename="embed_fail.pdf",
        content=pdf_bytes,
        db=db_session,
    )

    assert doc.status == KnowledgeStatus.FAILED
    assert doc.error_message is not None
    assert "Simulated embedding service failure" in doc.error_message
