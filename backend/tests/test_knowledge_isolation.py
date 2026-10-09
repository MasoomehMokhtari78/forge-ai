"""
Tests for domain isolation and cross-scope security boundaries.
"""

import pytest
from sqlalchemy import select

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.repository import IngestionStatus, Repository
from app.services.embedding import MockEmbeddingService
from app.services.engineering_knowledge import (
    DocumentAccessDeniedError,
    EngineeringKnowledgeService,
)
from tests.pdf_helpers import generate_test_pdf


async def test_document_cannot_be_accessed_through_another_knowledge_scope(db_session):
    """Verify that accessing document B through scope A raises DocumentAccessDeniedError."""
    scope_a = EngineeringKnowledge(name="Scope A")
    scope_b = EngineeringKnowledge(name="Scope B")
    db_session.add_all([scope_a, scope_b])
    await db_session.flush()

    doc_b = KnowledgeDocument(
        knowledge_id=scope_b.id,
        filename="doc_b.pdf",
        source_type="pdf",
        file_size_bytes=100,
    )
    db_session.add(doc_b)
    await db_session.flush()

    service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())

    # Accessing doc_b with scope_b succeeds
    fetched = await service.get_document(knowledge_id=scope_b.id, document_id=doc_b.id, db=db_session)
    assert fetched.id == doc_b.id

    # Accessing doc_b with scope_a fails with access denied
    with pytest.raises(DocumentAccessDeniedError):
        await service.get_document(knowledge_id=scope_a.id, document_id=doc_b.id, db=db_session)


async def test_document_cannot_be_deleted_through_another_knowledge_scope(db_session):
    """Verify that deleting document B through scope A is blocked."""
    scope_a = EngineeringKnowledge(name="Scope Alpha")
    scope_b = EngineeringKnowledge(name="Scope Beta")
    db_session.add_all([scope_a, scope_b])
    await db_session.flush()

    doc_b = KnowledgeDocument(
        knowledge_id=scope_b.id,
        filename="secret.pdf",
        source_type="pdf",
        file_size_bytes=100,
    )
    db_session.add(doc_b)
    await db_session.flush()

    service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())

    with pytest.raises(DocumentAccessDeniedError):
        await service.delete_document(knowledge_id=scope_a.id, document_id=doc_b.id, db=db_session)

    # Document still exists
    assert await db_session.get(KnowledgeDocument, doc_b.id) is not None


async def test_chunks_associated_with_correct_knowledge_and_document(db_session):
    """Verify chunks are strictly scoped to their parent knowledge scope and document."""
    scope_1 = EngineeringKnowledge(name="Domain 1")
    scope_2 = EngineeringKnowledge(name="Domain 2")
    db_session.add_all([scope_1, scope_2])
    await db_session.flush()

    service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())

    pdf_1 = generate_test_pdf(["Architecture and design patterns content for Scope 1."])
    pdf_2 = generate_test_pdf(["Architecture and design patterns content for Scope 2."])

    doc_1 = await service.ingest_document(knowledge_id=scope_1.id, filename="d1.pdf", content=pdf_1, db=db_session)
    doc_2 = await service.ingest_document(knowledge_id=scope_2.id, filename="d2.pdf", content=pdf_2, db=db_session)

    # Chunks for scope 1
    s1_chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == scope_1.id)
        )
    ).scalars().all()

    # Chunks for scope 2
    s2_chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == scope_2.id)
        )
    ).scalars().all()

    assert len(s1_chunks) == 1
    assert s1_chunks[0].document_id == doc_1.id
    assert "Scope 1" in s1_chunks[0].content

    assert len(s2_chunks) == 1
    assert s2_chunks[0].document_id == doc_2.id
    assert "Scope 2" in s2_chunks[0].content


async def test_deleting_knowledge_scope_leaves_no_orphan_chunks_and_does_not_affect_others(db_session):
    """Verify that deleting a scope deletes all its chunks without impacting another scope."""
    scope_to_delete = EngineeringKnowledge(name="Temporary Scope")
    scope_to_keep = EngineeringKnowledge(name="Permanent Scope")
    db_session.add_all([scope_to_delete, scope_to_keep])
    await db_session.flush()

    service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())

    pdf_del = generate_test_pdf(["Temporary chunk to be deleted"])
    pdf_keep = generate_test_pdf(["Permanent chunk to remain"])

    await service.ingest_document(knowledge_id=scope_to_delete.id, filename="temp.pdf", content=pdf_del, db=db_session)
    await service.ingest_document(knowledge_id=scope_to_keep.id, filename="keep.pdf", content=pdf_keep, db=db_session)

    # Delete scope_to_delete
    await service.delete_knowledge(knowledge_id=scope_to_delete.id, db=db_session)

    # Verify temp chunks are gone
    temp_chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == scope_to_delete.id)
        )
    ).scalars().all()
    assert len(temp_chunks) == 0

    # Verify keep chunks are intact
    keep_chunks = (
        await db_session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.knowledge_id == scope_to_keep.id)
        )
    ).scalars().all()
    assert len(keep_chunks) == 1
    assert "Permanent chunk" in keep_chunks[0].content


async def test_repository_and_knowledge_domains_are_strictly_separated(db_session):
    """Verify that repository code chunks and knowledge chunks exist in completely separate tables."""
    # Create repository with a code file and chunk
    repo = Repository(url="https://github.com/test/separation-repo", name="test/separation-repo", status=IngestionStatus.COMPLETED)
    db_session.add(repo)
    await db_session.flush()

    code_file = CodeFile(repository_id=repo.id, path="src/service.py", extension=".py", size_bytes=100)
    db_session.add(code_file)
    await db_session.flush()

    code_chunk = CodeChunk(
        file_id=code_file.id,
        chunk_index=0,
        content="class RepositoryService: pass",
        start_line=1,
        end_line=1,
        embedding=[0.1] * 384,
    )
    db_session.add(code_chunk)

    # Create knowledge scope with document and chunk
    knowledge = EngineeringKnowledge(name="Separation Knowledge Scope")
    db_session.add(knowledge)
    await db_session.flush()

    service = EngineeringKnowledgeService(embedding_service=MockEmbeddingService())
    pdf = generate_test_pdf(["Engineering Knowledge Architecture Concept"])
    await service.ingest_document(knowledge_id=knowledge.id, filename="arch.pdf", content=pdf, db=db_session)

    # Verify CodeChunk table only contains code chunk
    code_chunks = (await db_session.execute(select(CodeChunk))).scalars().all()
    assert len(code_chunks) == 1
    assert code_chunks[0].file_id == code_file.id

    # Verify KnowledgeChunk table only contains knowledge chunk
    knowledge_chunks = (await db_session.execute(select(KnowledgeChunk))).scalars().all()
    assert len(knowledge_chunks) == 1
    assert knowledge_chunks[0].knowledge_id == knowledge.id
