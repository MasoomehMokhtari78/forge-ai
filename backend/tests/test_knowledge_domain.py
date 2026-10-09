"""
Integration tests for the EngineeringKnowledge, KnowledgeDocument, and KnowledgeChunk ORM models.
"""

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument


async def test_create_engineering_knowledge(db_session):
    """Verify that an EngineeringKnowledge scope can be created with default fields."""
    knowledge = EngineeringKnowledge(
        name="Design Pattern Guidance",
        description="Definitions and examples of GoF and modern architectural patterns.",
    )
    db_session.add(knowledge)
    await db_session.flush()

    assert knowledge.id is not None
    assert knowledge.name == "Design Pattern Guidance"
    assert knowledge.status == KnowledgeStatus.PENDING
    assert knowledge.created_at is not None
    assert knowledge.updated_at is not None
    assert knowledge.error_message is None


async def test_get_engineering_knowledge_by_id(db_session):
    """Verify that an EngineeringKnowledge scope can be retrieved by primary key."""
    knowledge = EngineeringKnowledge(name="SOLID Principles")
    db_session.add(knowledge)
    await db_session.flush()

    fetched = await db_session.get(EngineeringKnowledge, knowledge.id)
    assert fetched is not None
    assert fetched.id == knowledge.id
    assert fetched.name == "SOLID Principles"


async def test_duplicate_knowledge_name_prevented(db_session):
    """Enforce unique constraint on knowledge scope names."""
    k1 = EngineeringKnowledge(name="Clean Architecture")
    db_session.add(k1)
    await db_session.flush()

    k2 = EngineeringKnowledge(name="Clean Architecture")
    db_session.add(k2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_knowledge_document_belongs_to_scope(db_session):
    """Verify KnowledgeDocument correctly links to EngineeringKnowledge."""
    knowledge = EngineeringKnowledge(name="Refactoring Guidelines")
    db_session.add(knowledge)
    await db_session.flush()

    doc = KnowledgeDocument(
        knowledge_id=knowledge.id,
        filename="refactoring.pdf",
        source_type="pdf",
        file_size_bytes=1024,
        status=KnowledgeStatus.PENDING,
    )
    db_session.add(doc)
    await db_session.flush()

    assert doc.id is not None
    assert doc.knowledge_id == knowledge.id
    assert doc.knowledge.name == "Refactoring Guidelines"


async def test_duplicate_document_filename_prevented_in_same_scope(db_session):
    """Enforce unique filename per knowledge scope."""
    knowledge = EngineeringKnowledge(name="Scope A")
    db_session.add(knowledge)
    await db_session.flush()

    d1 = KnowledgeDocument(
        knowledge_id=knowledge.id,
        filename="guide.pdf",
        source_type="pdf",
        file_size_bytes=500,
    )
    db_session.add(d1)
    await db_session.flush()

    d2 = KnowledgeDocument(
        knowledge_id=knowledge.id,
        filename="guide.pdf",
        source_type="pdf",
        file_size_bytes=800,
    )
    db_session.add(d2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_knowledge_chunk_belongs_to_document_and_scope(db_session):
    """Verify KnowledgeChunk links to document and knowledge scope with vector embedding."""
    knowledge = EngineeringKnowledge(name="Microservices Architecture")
    db_session.add(knowledge)
    await db_session.flush()

    doc = KnowledgeDocument(
        knowledge_id=knowledge.id,
        filename="microservices.pdf",
        source_type="pdf",
        file_size_bytes=2048,
    )
    db_session.add(doc)
    await db_session.flush()

    dim = settings.embedding_dimension
    test_embedding = [0.05] * dim

    chunk = KnowledgeChunk(
        knowledge_id=knowledge.id,
        document_id=doc.id,
        chunk_index=0,
        content="Service discovery and API gateways are key microservice patterns.",
        page_number=1,
        embedding=test_embedding,
    )
    db_session.add(chunk)
    await db_session.flush()

    assert chunk.id is not None
    assert chunk.knowledge_id == knowledge.id
    assert chunk.document_id == doc.id
    assert chunk.page_number == 1
    assert len(chunk.embedding) == dim


async def test_duplicate_chunk_indexes_prevented(db_session):
    """Enforce unique chunk_index per document."""
    knowledge = EngineeringKnowledge(name="Domain Driven Design")
    db_session.add(knowledge)
    await db_session.flush()

    doc = KnowledgeDocument(
        knowledge_id=knowledge.id,
        filename="ddd.pdf",
        source_type="pdf",
        file_size_bytes=1000,
    )
    db_session.add(doc)
    await db_session.flush()

    dim = settings.embedding_dimension
    c1 = KnowledgeChunk(
        knowledge_id=knowledge.id,
        document_id=doc.id,
        chunk_index=0,
        content="Aggregates and Entities",
        page_number=1,
        embedding=[0.1] * dim,
    )
    db_session.add(c1)
    await db_session.flush()

    c2 = KnowledgeChunk(
        knowledge_id=knowledge.id,
        document_id=doc.id,
        chunk_index=0,  # Duplicate index
        content="Value Objects",
        page_number=2,
        embedding=[0.2] * dim,
    )
    db_session.add(c2)

    with pytest.raises(IntegrityError):
        await db_session.flush()


async def test_delete_knowledge_cascades_documents_and_chunks(db_session):
    """Verify that deleting an EngineeringKnowledge scope cascades to all documents and chunks."""
    knowledge = EngineeringKnowledge(name="Cascade Scope")
    db_session.add(knowledge)
    await db_session.flush()

    doc = KnowledgeDocument(
        knowledge_id=knowledge.id,
        filename="cascade_doc.pdf",
        source_type="pdf",
        file_size_bytes=500,
    )
    db_session.add(doc)
    await db_session.flush()

    dim = settings.embedding_dimension
    chunk = KnowledgeChunk(
        knowledge_id=knowledge.id,
        document_id=doc.id,
        chunk_index=0,
        content="Cascade chunk content",
        page_number=1,
        embedding=[0.3] * dim,
    )
    db_session.add(chunk)
    await db_session.flush()

    # Save IDs into local variables before deleting/expiring
    knowledge_id = knowledge.id
    doc_id = doc.id
    chunk_id = chunk.id

    # Verify rows exist
    assert await db_session.get(EngineeringKnowledge, knowledge_id) is not None
    assert await db_session.get(KnowledgeDocument, doc_id) is not None
    assert await db_session.get(KnowledgeChunk, chunk_id) is not None

    # Delete knowledge scope
    await db_session.delete(knowledge)
    await db_session.flush()
    db_session.expire_all()

    # Verify cascaded deletion in database
    assert await db_session.get(EngineeringKnowledge, knowledge_id) is None
    assert await db_session.get(KnowledgeDocument, doc_id) is None
    assert await db_session.get(KnowledgeChunk, chunk_id) is None
