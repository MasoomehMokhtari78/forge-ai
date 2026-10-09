"""
Integration tests for KnowledgeRetrievalService.
"""

from uuid import uuid4

import pytest

from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.services.embedding import MockEmbeddingService
from app.services.engineering_knowledge import KnowledgeNotFoundError
from app.services.knowledge_retrieval import KnowledgeRetrievalService


async def test_knowledge_retrieval_strictly_scoped(db_session):
    """Verify that knowledge retrieval for scope A never returns chunks belonging to scope B."""
    scope_a = EngineeringKnowledge(name="Scope A Design Patterns")
    scope_b = EngineeringKnowledge(name="Scope B Clean Code")
    db_session.add_all([scope_a, scope_b])
    await db_session.flush()

    doc_a = KnowledgeDocument(
        knowledge_id=scope_a.id,
        filename="patterns.pdf",
        status=KnowledgeStatus.COMPLETED,
    )
    doc_b = KnowledgeDocument(
        knowledge_id=scope_b.id,
        filename="cleancode.pdf",
        status=KnowledgeStatus.COMPLETED,
    )
    db_session.add_all([doc_a, doc_b])
    await db_session.flush()

    mock_emb = MockEmbeddingService()
    emb_a = (await mock_emb.get_embeddings(["Factory and Singleton patterns"]))[0]
    emb_b = (await mock_emb.get_embeddings(["Functions should do one thing"]))[0]

    chunk_a = KnowledgeChunk(
        knowledge_id=scope_a.id,
        document_id=doc_a.id,
        chunk_index=0,
        content="Factory pattern decouples object creation from client code.",
        page_number=12,
        embedding=emb_a,
    )
    chunk_b = KnowledgeChunk(
        knowledge_id=scope_b.id,
        document_id=doc_b.id,
        chunk_index=0,
        content="Clean code functions must be small and do one thing well.",
        page_number=45,
        embedding=emb_b,
    )
    db_session.add_all([chunk_a, chunk_b])
    await db_session.flush()

    service = KnowledgeRetrievalService(embedding_service=mock_emb)

    # Query scope A
    results_a = await service.retrieve(
        knowledge_id=scope_a.id,
        query="Factory pattern creation",
        db=db_session,
        top_k=5,
    )

    assert len(results_a) == 1
    assert results_a[0].chunk_id == chunk_a.id
    assert results_a[0].knowledge_id == scope_a.id
    assert results_a[0].filename == "patterns.pdf"
    assert results_a[0].page_number == 12
    assert "Factory pattern" in results_a[0].content

    # Query scope B
    results_b = await service.retrieve(
        knowledge_id=scope_b.id,
        query="Functions single responsibility",
        db=db_session,
        top_k=5,
    )

    assert len(results_b) == 1
    assert results_b[0].chunk_id == chunk_b.id
    assert results_b[0].knowledge_id == scope_b.id
    assert results_b[0].filename == "cleancode.pdf"
    assert results_b[0].page_number == 45


async def test_knowledge_retrieval_empty_query_returns_empty(db_session):
    """Verify that an empty or whitespace query returns an empty result list without DB queries."""
    scope = EngineeringKnowledge(name="Empty Query Scope")
    db_session.add(scope)
    await db_session.flush()

    service = KnowledgeRetrievalService(embedding_service=MockEmbeddingService())
    results = await service.retrieve(
        knowledge_id=scope.id,
        query="   ",
        db=db_session,
    )
    assert results == []


async def test_knowledge_retrieval_non_existent_scope_raises(db_session):
    """Verify that querying a non-existent knowledge scope raises KnowledgeNotFoundError."""
    service = KnowledgeRetrievalService(embedding_service=MockEmbeddingService())
    with pytest.raises(KnowledgeNotFoundError):
        await service.retrieve(
            knowledge_id=uuid4(),
            query="test query",
            db=db_session,
        )


async def test_knowledge_retrieval_ignores_uncompleted_documents(db_session):
    """Verify that chunks belonging to documents that failed or are still processing are ignored."""
    scope = EngineeringKnowledge(name="Status Filtering Scope")
    db_session.add(scope)
    await db_session.flush()

    doc_pending = KnowledgeDocument(
        knowledge_id=scope.id,
        filename="pending.pdf",
        status=KnowledgeStatus.PROCESSING,
    )
    db_session.add(doc_pending)
    await db_session.flush()

    mock_emb = MockEmbeddingService()
    emb = (await mock_emb.get_embeddings(["Processing text"]))[0]

    chunk = KnowledgeChunk(
        knowledge_id=scope.id,
        document_id=doc_pending.id,
        chunk_index=0,
        content="This chunk belongs to a processing document.",
        page_number=1,
        embedding=emb,
    )
    db_session.add(chunk)
    await db_session.flush()

    service = KnowledgeRetrievalService(embedding_service=mock_emb)
    results = await service.retrieve(
        knowledge_id=scope.id,
        query="Processing text",
        db=db_session,
    )
    assert len(results) == 0
