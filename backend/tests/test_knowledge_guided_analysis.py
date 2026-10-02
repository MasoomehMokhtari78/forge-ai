"""
Unit and integration tests for KnowledgeGuidedAnalysisService.
"""

from uuid import uuid4

import pytest

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.repository import IngestionStatus, Repository
from app.schemas.analysis import CodeScope, CodeScopeType
from app.services.embedding import MockEmbeddingService
from app.services.knowledge_guided_analysis import (
    AnalysisKnowledgeNotReadyError,
    AnalysisRepositoryNotReadyError,
    FileNotFoundInRepositoryError,
    KnowledgeGuidedAnalysisService,
)
from app.services.knowledge_retrieval import KnowledgeRetrievalService
from app.services.llm import MockLLMService
from app.services.retrieval import RetrievalService


async def setup_test_repository_and_knowledge(db_session):
    """Fixture helper creating a completed repository and completed knowledge scope with chunks."""
    mock_emb = MockEmbeddingService()

    # 1. Repository
    repo = Repository(
        url="https://github.com/test/analysis-repo",
        name="test/analysis-repo",
        status=IngestionStatus.COMPLETED,
    )
    db_session.add(repo)
    await db_session.flush()

    file_payment = CodeFile(
        repository_id=repo.id,
        path="src/services/payment.py",
        extension=".py",
        size_bytes=450,
    )
    file_user = CodeFile(
        repository_id=repo.id,
        path="src/models/user.py",
        extension=".py",
        size_bytes=200,
    )
    db_session.add_all([file_payment, file_user])
    await db_session.flush()

    emb_pay = (await mock_emb.get_embeddings(["Payment gateway processor and strategy execution"]))[0]
    emb_user = (await mock_emb.get_embeddings(["User entity and account representation"]))[0]

    chunk_pay = CodeChunk(
        file_id=file_payment.id,
        chunk_index=0,
        content="class PaymentProcessor:\n    def process(self, payment_type):\n        if payment_type == 'paypal': pass",
        start_line=1,
        end_line=25,
        embedding=emb_pay,
    )
    chunk_user = CodeChunk(
        file_id=file_user.id,
        chunk_index=0,
        content="class User:\n    id: int\n    name: str",
        start_line=1,
        end_line=15,
        embedding=emb_user,
    )
    db_session.add_all([chunk_pay, chunk_user])

    # 2. Knowledge Scope
    knowledge = EngineeringKnowledge(
        name="Architecture & Design Patterns",
        status=KnowledgeStatus.COMPLETED,
    )
    db_session.add(knowledge)
    await db_session.flush()

    doc = KnowledgeDocument(
        knowledge_id=knowledge.id,
        filename="DesignPatterns.pdf",
        status=KnowledgeStatus.COMPLETED,
    )
    db_session.add(doc)
    await db_session.flush()

    emb_strat = (await mock_emb.get_embeddings(["Strategy pattern defines interchangeable algorithms"]))[0]

    k_chunk = KnowledgeChunk(
        knowledge_id=knowledge.id,
        document_id=doc.id,
        chunk_index=0,
        content="Strategy Pattern defines a family of algorithms, encapsulates each one, and makes them interchangeable.",
        page_number=87,
        embedding=emb_strat,
    )
    db_session.add(k_chunk)
    await db_session.flush()

    service = KnowledgeGuidedAnalysisService(
        retrieval_service=RetrievalService(embedding_service=mock_emb),
        knowledge_retrieval_service=KnowledgeRetrievalService(embedding_service=mock_emb),
        llm_service=MockLLMService(),
    )

    return repo, knowledge, file_payment, service


async def test_combined_analysis_repository_scope(db_session):
    """Verify end-to-end analysis combining whole-repository code search and knowledge retrieval."""
    repo, knowledge, _, service = await setup_test_repository_and_knowledge(db_session)

    resp = await service.analyze(
        repository_id=repo.id,
        knowledge_id=knowledge.id,
        code_scope=CodeScope(type=CodeScopeType.REPOSITORY),
        question="What pattern would help refactor the payment processor?",
        db=db_session,
    )

    assert resp.answer is not None
    assert "[MOCK LLM RESPONSE]" in resp.answer
    assert len(resp.sources) >= 2

    repo_sources = [s for s in resp.sources if s.type == "repository"]
    knowledge_sources = [s for s in resp.sources if s.type == "knowledge"]

    assert len(repo_sources) >= 1
    assert "src/services/payment.py" in repo_sources[0].path
    assert repo_sources[0].start_line == 1
    assert repo_sources[0].end_line == 25
    assert repo_sources[0].source_id.startswith("src_")

    assert len(knowledge_sources) >= 1
    assert knowledge_sources[0].path == "DesignPatterns.pdf"
    assert knowledge_sources[0].page_number == 87
    assert knowledge_sources[0].label == "DesignPatterns.pdf, page 87"


async def test_file_scoped_analysis(db_session):
    """Verify that file scope restricts code evidence strictly to the specified file."""
    repo, knowledge, file_payment, service = await setup_test_repository_and_knowledge(db_session)

    resp = await service.analyze(
        repository_id=repo.id,
        knowledge_id=knowledge.id,
        code_scope=CodeScope(type=CodeScopeType.FILE, path="src/services/payment.py"),
        question="Analyze the architecture of this file.",
        db=db_session,
    )

    repo_sources = [s for s in resp.sources if s.type == "repository"]
    assert len(repo_sources) == 1
    assert repo_sources[0].path == "src/services/payment.py"


async def test_file_not_in_repository_rejected(db_session):
    """Verify that targeting a file not present in the repository raises FileNotFoundInRepositoryError."""
    repo, knowledge, _, service = await setup_test_repository_and_knowledge(db_session)

    with pytest.raises(FileNotFoundInRepositoryError):
        await service.analyze(
            repository_id=repo.id,
            knowledge_id=knowledge.id,
            code_scope=CodeScope(type=CodeScopeType.FILE, path="src/services/non_existent.py"),
            question="Analyze non-existent file",
            db=db_session,
        )


async def test_cross_repository_file_scope_blocked(db_session):
    """Verify that a file belonging to repository B cannot be queried through repository A."""
    repo_a, knowledge, _, service = await setup_test_repository_and_knowledge(db_session)

    repo_b = Repository(url="https://github.com/test/repo-b", name="test/repo-b", status=IngestionStatus.COMPLETED)
    db_session.add(repo_b)
    await db_session.flush()

    file_b = CodeFile(repository_id=repo_b.id, path="src/b_secret.py", extension=".py", size_bytes=100)
    db_session.add(file_b)
    await db_session.flush()

    # Querying repo_a with file_b's path must raise FileNotFoundInRepositoryError
    with pytest.raises(FileNotFoundInRepositoryError):
        await service.analyze(
            repository_id=repo_a.id,
            knowledge_id=knowledge.id,
            code_scope=CodeScope(type=CodeScopeType.FILE, path="src/b_secret.py"),
            question="Access file B through repo A",
            db=db_session,
        )


async def test_analysis_missing_knowledge_evidence_safeguard(db_session):
    """Verify that when no relevant knowledge chunks exist, the model acknowledges it and cites no knowledge."""
    repo, _, _, service = await setup_test_repository_and_knowledge(db_session)

    # Empty knowledge scope with no completed documents
    empty_knowledge = EngineeringKnowledge(name="Empty Knowledge Scope", status=KnowledgeStatus.COMPLETED)
    db_session.add(empty_knowledge)
    await db_session.flush()

    resp = await service.analyze(
        repository_id=repo.id,
        knowledge_id=empty_knowledge.id,
        code_scope=CodeScope(type=CodeScopeType.REPOSITORY),
        question="Refactoring recommendation question",
        db=db_session,
    )

    assert "does not provide enough evidence to support a recommendation" in resp.answer
    # Knowledge citations must NOT be fabricated
    knowledge_sources = [s for s in resp.sources if s.type == "knowledge"]
    assert len(knowledge_sources) == 0


async def test_analysis_missing_repository_evidence_safeguard(db_session):
    """Verify that when repository evidence is missing, the model acknowledges it and cites no repo code."""
    _, knowledge, _, service = await setup_test_repository_and_knowledge(db_session)

    empty_repo = Repository(url="https://github.com/test/empty-repo", name="test/empty-repo", status=IngestionStatus.COMPLETED)
    db_session.add(empty_repo)
    await db_session.flush()

    resp = await service.analyze(
        repository_id=empty_repo.id,
        knowledge_id=knowledge.id,
        code_scope=CodeScope(type=CodeScopeType.REPOSITORY),
        question="Where is the non-existent feature handled?",
        db=db_session,
    )

    assert "could not find enough relevant repository evidence" in resp.answer
    repo_sources = [s for s in resp.sources if s.type == "repository"]
    assert len(repo_sources) == 0


async def test_unready_repository_rejected(db_session):
    """Verify that a repository with PENDING ingestion status is rejected."""
    _, knowledge, _, service = await setup_test_repository_and_knowledge(db_session)

    pending_repo = Repository(url="https://github.com/test/pending-repo", name="test/pending-repo", status=IngestionStatus.PENDING)
    db_session.add(pending_repo)
    await db_session.flush()

    with pytest.raises(AnalysisRepositoryNotReadyError):
        await service.analyze(
            repository_id=pending_repo.id,
            knowledge_id=knowledge.id,
            code_scope=CodeScope(type=CodeScopeType.REPOSITORY),
            question="Analyze pending repo",
            db=db_session,
        )


async def test_failed_knowledge_scope_rejected(db_session):
    """Verify that a knowledge scope in FAILED status is rejected."""
    repo, _, _, service = await setup_test_repository_and_knowledge(db_session)

    failed_knowledge = EngineeringKnowledge(name="Failed Scope", status=KnowledgeStatus.FAILED)
    db_session.add(failed_knowledge)
    await db_session.flush()

    with pytest.raises(AnalysisKnowledgeNotReadyError):
        await service.analyze(
            repository_id=repo.id,
            knowledge_id=failed_knowledge.id,
            code_scope=CodeScope(type=CodeScopeType.REPOSITORY),
            question="Analyze with failed knowledge",
            db=db_session,
        )
