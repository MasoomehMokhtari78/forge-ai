"""
Unit and integration tests for Hybrid Code Retrieval (Semantic + Lexical + Path + RRF).
"""

from uuid import UUID, uuid4
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.services.embedding import MockEmbeddingService
from app.services.retrieval import RetrievalService, extract_query_tokens
from app.services.retrieval_metrics import (
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


# ===========================================================================
# 1. Token Extraction Unit Tests
# ===========================================================================

def test_extract_query_tokens_splits_camel_and_snake_case():
    tokens = extract_query_tokens("Where is getFileContent and auth_service implemented?")
    assert "getfilecontent" in tokens
    assert "file" in tokens
    assert "content" in tokens
    assert "auth_service" in tokens
    assert "auth" in tokens
    assert "service" in tokens
    assert "where" not in tokens
    assert "is" not in tokens
    assert "and" not in tokens


def test_extract_query_tokens_generates_stems_for_plurals():
    tokens = extract_query_tokens("Where are projects and styles configured?")
    assert "projects" in tokens
    assert "project" in tokens
    assert "styles" in tokens
    assert "style" in tokens


def test_extract_query_tokens_handles_empty_and_punctuation():
    assert extract_query_tokens("") == []
    assert extract_query_tokens("??? !!! ...") == []


# ===========================================================================
# 2. Retrieval Metrics Unit Tests
# ===========================================================================

def test_retrieval_metrics_calculations():
    retrieved = ["src/auth.py", "package-lock.json", "src/models.py"]
    relevant = {"src/auth.py", "src/models.py"}

    # Precision@2: 1 hit in 2 results -> 0.5
    assert precision_at_k(retrieved, relevant, k=2) == 0.5
    # Precision@3: 2 hits in 3 results -> 2/3
    assert pytest.approx(precision_at_k(retrieved, relevant, k=3), rel=1e-2) == 2 / 3

    # Recall@2: 1 of 2 relevant retrieved -> 0.5
    assert recall_at_k(retrieved, relevant, k=2) == 0.5
    # Recall@3: 2 of 2 relevant retrieved -> 1.0
    assert recall_at_k(retrieved, relevant, k=3) == 1.0

    # Reciprocal Rank: first hit at rank 1 -> 1.0
    assert reciprocal_rank(retrieved, relevant) == 1.0

    # If first hit at rank 2:
    assert reciprocal_rank(["irrelevant.ts", "src/auth.py"], relevant) == 0.5

    # Mean Reciprocal Rank
    evals = [
        (["src/auth.py", "other.py"], {"src/auth.py"}),       # RR = 1.0
        (["other.py", "src/models.py"], {"src/models.py"}),  # RR = 0.5
    ]
    assert mean_reciprocal_rank(evals) == 0.75


# ===========================================================================
# 3. RRF Fusion & Lock-File Deprioritization Unit Tests
# ===========================================================================

def test_fuse_and_rerank_deprioritizes_lock_files():
    retrieval_service = RetrievalService(embedding_service=MockEmbeddingService())

    cid_code = uuid4()
    chunk_code = CodeChunk(
        id=cid_code, file_id=uuid4(), chunk_index=0,
        content="const x = 1;", start_line=1, end_line=10, embedding=[]
    )
    cid_lock = uuid4()
    chunk_lock = CodeChunk(
        id=cid_lock, file_id=uuid4(), chunk_index=0,
        content="{ dependencies: {} }", start_line=1, end_line=10, embedding=[]
    )

    # Both appear in semantic candidates with lock slightly ahead
    semantic_candidates = [
        (chunk_lock, "package-lock.json", 0.95),
        (chunk_code, "src/components/Projects.tsx", 0.90),
    ]
    # Code file also appears in lexical and path candidates
    lexical_candidates = [
        (chunk_code, "src/components/Projects.tsx", 0.3),
    ]
    path_candidates = [
        (chunk_code, "src/components/Projects.tsx", 3.0),
    ]

    results = retrieval_service.fuse_and_rerank(
        semantic_candidates=semantic_candidates,
        lexical_candidates=lexical_candidates,
        path_candidates=path_candidates,
        top_k=5,
    )

    assert len(results) == 2
    # Code chunk must rank above lock file
    assert results[0].path == "src/components/Projects.tsx"
    assert results[1].path == "package-lock.json"
    assert results[0].similarity == 1.0
    assert results[0].similarity > results[1].similarity


# ===========================================================================
# 4. Deterministic Integration Tests with Database Fixtures
# ===========================================================================

async def _create_test_repo(db: AsyncSession, name: str = "test/hybrid-repo") -> Repository:
    repo = Repository(
        url=f"https://github.com/{name}-{uuid4().hex[:6]}",
        name=name,
        status=IngestionStatus.COMPLETED,
    )
    db.add(repo)
    await db.flush()
    return repo


async def _add_test_file_and_chunk(
    db: AsyncSession,
    repo_id: UUID,
    path: str,
    content: str,
    embedding: list[float],
    start_line: int = 1,
    end_line: int = 30,
    chunk_index: int = 0,
) -> CodeChunk:
    code_file = CodeFile(
        repository_id=repo_id,
        path=path,
        extension=f".{path.split('.')[-1]}" if "." in path else "",
        size_bytes=len(content.encode("utf-8")),
    )
    db.add(code_file)
    await db.flush()

    chunk = CodeChunk(
        file_id=code_file.id,
        chunk_index=chunk_index,
        content=content,
        start_line=start_line,
        end_line=end_line,
        embedding=embedding,
    )
    db.add(chunk)
    await db.flush()
    return chunk


async def test_case_1_projects_section_ranks_above_noise_files(db_session: AsyncSession):
    """Case 1: 'Where is the projects section handled or rendered?'
    Expected: app/page.tsx or components/Projects/Projects.tsx rank above package-lock.json and components.json.
    """
    repo = await _create_test_repo(db_session)
    embedder = MockEmbeddingService(dimension=settings.embedding_dimension)
    retrieval_service = RetrievalService(embedding_service=embedder)

    query = "Where is the projects section handled or rendered?"
    embeddings = await embedder.get_embeddings([
        query,
        "import { Projects } from '@/components/Projects/Projects'; <div id='projects'><Projects /></div>",
        "export function Projects() { const projects = [{ title: 'Finance+' }]; return <div>My Projects</div>; }",
        "lockfileVersion 3 dependencies node_modules projects section mock package metadata",
        "schema https ui shadcn components new-york",
    ])

    await _add_test_file_and_chunk(
        db_session, repo.id, "app/page.tsx",
        "import { Projects } from '@/components/Projects/Projects'; <div id='projects'><Projects /></div>",
        embeddings[1]
    )
    await _add_test_file_and_chunk(
        db_session, repo.id, "components/Projects/Projects.tsx",
        "export function Projects() { const projects = [{ title: 'Finance+' }]; return <div>My Projects</div>; }",
        embeddings[2]
    )
    await _add_test_file_and_chunk(
        db_session, repo.id, "package-lock.json",
        "lockfileVersion 3 dependencies node_modules projects section mock package metadata",
        embeddings[3]
    )
    await _add_test_file_and_chunk(
        db_session, repo.id, "components.json",
        "schema https ui shadcn components new-york",
        embeddings[4]
    )

    results = await retrieval_service.search(
        repository_id=repo.id,
        query=query,
        db=db_session,
        top_k=4,
    )

    assert len(results) > 0
    top_paths = [r.path for r in results]

    # At least one authoritative project file must be in the top 2
    assert any(p in ("app/page.tsx", "components/Projects/Projects.tsx") for p in top_paths[:2])

    # package-lock.json must rank below the primary code implementations
    idx_lock = top_paths.index("package-lock.json")
    idx_project = min(
        top_paths.index(p)
        for p in ("app/page.tsx", "components/Projects/Projects.tsx")
        if p in top_paths
    )
    assert idx_project < idx_lock

    # Calculate and verify Precision@2 and MRR
    relevant = {"app/page.tsx", "components/Projects/Projects.tsx"}
    p2 = precision_at_k(top_paths, relevant, k=2)
    rr = reciprocal_rank(top_paths, relevant)
    assert p2 >= 0.5
    assert rr == 1.0


async def test_case_2_global_styles_and_fonts_rank_above_noise_files(db_session: AsyncSession):
    """Case 2: 'Where are global styles and fonts configured?'
    Expected: app/layout.tsx and/or app/globals.css rank above package-lock.json.
    """
    repo = await _create_test_repo(db_session)
    embedder = MockEmbeddingService(dimension=settings.embedding_dimension)
    retrieval_service = RetrievalService(embedding_service=embedder)

    query = "Where are global styles and fonts configured?"
    embeddings = await embedder.get_embeddings([
        query,
        "@tailwind base; @tailwind components; :root { --background: #ffffff; }",
        "import './globals.css'; import { Roboto_Mono } from 'next/font/google'; export default function RootLayout() {}",
        "lockfileVersion 3 dependencies styles font global configuration package metadata",
    ])

    await _add_test_file_and_chunk(
        db_session, repo.id, "app/globals.css",
        "@tailwind base; @tailwind components; :root { --background: #ffffff; }",
        embeddings[1]
    )
    await _add_test_file_and_chunk(
        db_session, repo.id, "app/layout.tsx",
        "import './globals.css'; import { Roboto_Mono } from 'next/font/google'; export default function RootLayout() {}",
        embeddings[2]
    )
    await _add_test_file_and_chunk(
        db_session, repo.id, "package-lock.json",
        "lockfileVersion 3 dependencies styles font global configuration package metadata",
        embeddings[3]
    )

    results = await retrieval_service.search(
        repository_id=repo.id,
        query=query,
        db=db_session,
        top_k=3,
    )

    assert len(results) > 0
    top_paths = [r.path for r in results]

    # Global styles/layout must be in top 2
    assert any(p in ("app/layout.tsx", "app/globals.css") for p in top_paths[:2])

    # package-lock.json must rank below relevant styling files
    idx_lock = top_paths.index("package-lock.json")
    idx_style = min(
        top_paths.index(p)
        for p in ("app/layout.tsx", "app/globals.css")
        if p in top_paths
    )
    assert idx_style < idx_lock

    relevant = {"app/layout.tsx", "app/globals.css"}
    p2 = precision_at_k(top_paths, relevant, k=2)
    rr = reciprocal_rank(top_paths, relevant)
    assert p2 >= 0.5
    assert rr == 1.0


async def test_case_3_code_identifier_query_ranks_implementation_first(db_session: AsyncSession):
    """Case 3: Code identifier query e.g. 'Where is CardSpotlight implemented?'
    Expected: components/ui/card-spotlight.tsx ranks at rank 1.
    """
    repo = await _create_test_repo(db_session)
    embedder = MockEmbeddingService(dimension=settings.embedding_dimension)
    retrieval_service = RetrievalService(embedding_service=embedder)

    query = "Where is CardSpotlight component implemented?"
    embeddings = await embedder.get_embeddings([
        query,
        "export function CardSpotlight({ children }) { return <div className='spotlight'>{children}</div>; }",
        "export function Button({ label }) { return <button>{label}</button>; }",
    ])

    await _add_test_file_and_chunk(
        db_session, repo.id, "components/ui/card-spotlight.tsx",
        "export function CardSpotlight({ children }) { return <div className='spotlight'>{children}</div>; }",
        embeddings[1]
    )
    await _add_test_file_and_chunk(
        db_session, repo.id, "components/ui/button.tsx",
        "export function Button({ label }) { return <button>{label}</button>; }",
        embeddings[2]
    )

    results = await retrieval_service.search(
        repository_id=repo.id,
        query=query,
        db=db_session,
        top_k=2,
    )

    assert len(results) > 0
    assert results[0].path == "components/ui/card-spotlight.tsx"
    assert results[0].similarity == 1.0


async def test_case_4_semantic_concept_without_exact_word_overlap(db_session: AsyncSession):
    """Case 4: Natural language query benefiting from semantic retrieval.
    Query: 'author background and personal introduction'
    Expected: components/Introduction/Introduction.tsx is retrieved in top ranks via semantic signal.
    """
    repo = await _create_test_repo(db_session)
    embedder = MockEmbeddingService(dimension=settings.embedding_dimension)
    retrieval_service = RetrievalService(embedding_service=embedder)

    query = "author background and personal introduction"
    # Embeddings: query and target have high semantic similarity
    embeddings = await embedder.get_embeddings([
        query,
        query,  # Exact semantic match
        "completely unrelated code snippet with no relevance",
    ])

    await _add_test_file_and_chunk(
        db_session, repo.id, "components/Introduction/Introduction.tsx",
        "export function Introduction() { return <div>Software engineer biography</div>; }",
        embeddings[1]
    )
    await _add_test_file_and_chunk(
        db_session, repo.id, "components/ui/textarea.tsx",
        "export function Textarea() { return <textarea />; }",
        embeddings[2]
    )

    results = await retrieval_service.search(
        repository_id=repo.id,
        query=query,
        db=db_session,
        top_k=2,
    )

    assert len(results) > 0
    assert results[0].path == "components/Introduction/Introduction.tsx"
