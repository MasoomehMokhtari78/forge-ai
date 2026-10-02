"""
Real LLM Behavioral Evaluation Suite for ForgeAI Knowledge-Guided Analysis Pipeline.

Executes knowledge-guided code analysis queries against real pgvector retrieval
(repository code + engineering knowledge PDF), prompt/context building, and the local
Ollama LLM (qwen2.5-coder:7b), verifying:
- Case 1 (Recommendation): Grounded pattern recommendation based on retrieved reference.
- Case 2 (Resemblance): Architectural resemblance identification between code and knowledge.
- Case 3 (Insufficient Knowledge): Grounding limitation acknowledgement when reference lacks evidence.
"""

import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.repository import IngestionStatus, Repository
from app.schemas.analysis import AnalysisResponse, CodeScope, CodeScopeType
from app.services.engineering_knowledge import EngineeringKnowledgeService
from app.services.knowledge_guided_analysis import KnowledgeGuidedAnalysisService
from app.services.llm import OllamaLLMService
def generate_test_pdf(pages: list[str]) -> bytes:
    """Generate a valid, deterministic PDF byte stream containing text on each page."""
    lines = ["%PDF-1.4"]
    offsets = []

    # Object 1: Catalog
    offsets.append(sum(len(l) + 1 for l in lines))
    lines.append("1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj")

    font_id = 3 + len(pages) * 2

    # Object 2: Pages
    offsets.append(sum(len(l) + 1 for l in lines))
    kids = " ".join(f"{3 + i*2} 0 R" for i in range(len(pages)))
    lines.append(f"2 0 obj\n<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>\nendobj")

    for i, page_text in enumerate(pages):
        page_id = 3 + i * 2
        content_id = page_id + 1
        safe_text = page_text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream_text = f"BT /F1 12 Tf 72 712 Td ({safe_text}) Tj ET"

        offsets.append(sum(len(l) + 1 for l in lines))
        lines.append(
            f"{page_id} 0 obj\n"
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_id} 0 R >>\nendobj"
        )

        offsets.append(sum(len(l) + 1 for l in lines))
        lines.append(
            f"{content_id} 0 obj\n<< /Length {len(stream_text)} >>\nstream\n{stream_text}\nendstream\nendobj"
        )

    # Font object
    offsets.append(sum(len(l) + 1 for l in lines))
    lines.append(f"{font_id} 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj")

    # Cross-reference table
    xref_offset = sum(len(l) + 1 for l in lines)
    total_objs = font_id + 1
    lines.append(f"xref\n0 {total_objs}\n0000000000 65535 f ")
    for off in offsets:
        lines.append(f"{off:010d} 00000 n ")
    lines.append(f"trailer\n<< /Size {total_objs} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF")

    return "\n".join(lines).encode("latin-1")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("knowledge_eval")

EVAL_KNOWLEDGE_NAME = "Design Patterns Reference Guide"
EVAL_DOCUMENT_NAME = "design_patterns_reference.pdf"

PAGE_1_STRATEGY = """Design Patterns Reference Guide: Strategy Pattern

Definition:
The Strategy pattern is a behavioral design pattern that defines a family of algorithms, encapsulates each one, and makes them interchangeable. Strategy lets the algorithm vary independently from clients that use it.

Structure and Participants:
- Strategy: An interface or protocol common to all supported algorithm variations.
- Concrete Strategies: Classes that implement different variations of the algorithm.
- Context: Maintains a reference to a Strategy object and delegates execution to it.

Applicability:
- Use Strategy when you want to use different variants of an algorithm within an object and be able to switch between them at runtime.
- Use Strategy when you have multiple related classes that differ only in their behavior.
- Use Strategy to isolate business logic from algorithm implementation details.

Benefits:
- Clean adherence to Open/Closed Principle: you can introduce new strategies without modifying context code.
- Replaces conditional logic with polymorphic composition."""

PAGE_2_FACTORY = """Design Patterns Reference Guide: Factory Method Pattern

Definition:
The Factory Method is a creational design pattern that provides an interface for creating objects, but allows factory functions or subclasses to alter the type of objects that will be created.

Structure and Participants:
- Product Interface: Declares the interface for all objects that can be produced.
- Concrete Products: Different implementations of the product interface.
- Creator / Factory: Declares factory functions that return product instances.

Applicability:
- Use Factory Method when you do not know beforehand the exact types and dependencies of objects.
- Use Factory Method when you want to provide users an extensible way to configure components.

Benefits:
- Eliminates tight coupling between creator and concrete products.
- Single Responsibility Principle: Object creation code is centralized."""


EVALUATION_CASES: list[dict[str, Any]] = [
    {
        "id": "case-1-recommendation",
        "name": "Case 1 — Recommendation",
        "question": (
            "Based on the selected engineering knowledge, what pattern would you suggest "
            "for switching between different embedding implementations in backend/app/services/embedding.py?"
        ),
        "code_scope": {
            "type": "file",
            "path": "backend/app/services/embedding.py",
        },
        "checks": {
            "min_repo_sources": 1,
            "min_knowledge_sources": 1,
            "expected_knowledge_terms": ["strategy", "open/closed", "algorithm"],
            "expected_repo_files": ["backend/app/services/embedding.py"],
            "insufficient_knowledge_expected": False,
        },
    },
    {
        "id": "case-2-resemblance",
        "name": "Case 2 — Resemblance",
        "question": (
            "Does the implementation of EmbeddingService and get_default_embedding_service "
            "in backend/app/services/embedding.py resemble a pattern described in the selected knowledge?"
        ),
        "code_scope": {
            "type": "file",
            "path": "backend/app/services/embedding.py",
        },
        "checks": {
            "min_repo_sources": 1,
            "min_knowledge_sources": 1,
            "expected_knowledge_terms": ["strategy", "factory", "interface", "protocol"],
            "expected_repo_files": ["backend/app/services/embedding.py"],
            "insufficient_knowledge_expected": False,
        },
    },
    {
        "id": "case-3-insufficient-knowledge",
        "name": "Case 3 — Insufficient Knowledge",
        "question": (
            "Based on the selected engineering knowledge, what architecture pattern would you recommend "
            "for CQRS, Event Sourcing, and distributed Saga transactions across microservices in this codebase?"
        ),
        "code_scope": {
            "type": "file",
            "path": "backend/app/services/embedding.py",
        },
        "checks": {
            "insufficient_knowledge_expected": True,
            "refusal_phrases": [
                "does not provide enough evidence",
                "not described",
                "not covered",
                "does not contain",
                "no mention",
                "not found in the selected",
                "insufficient",
                "could not find",
            ],
        },
    },
]


async def ensure_eval_knowledge(session: AsyncSession) -> EngineeringKnowledge:
    """Ensure that the evaluation engineering knowledge reference exists and is completed."""
    stmt = select(EngineeringKnowledge).where(EngineeringKnowledge.name == EVAL_KNOWLEDGE_NAME)
    res = await session.execute(stmt)
    knowledge = res.scalar_one_or_none()

    service = EngineeringKnowledgeService()

    if knowledge is None:
        logger.info(f"Creating evaluation engineering knowledge: '{EVAL_KNOWLEDGE_NAME}'")
        knowledge = await service.create_knowledge(
            name=EVAL_KNOWLEDGE_NAME,
            description="Reference guide covering Strategy and Factory Method patterns for behavioral evaluation.",
            db=session,
        )

    # Check if document is already ingested
    doc_stmt = select(KnowledgeDocument).where(
        KnowledgeDocument.knowledge_id == knowledge.id,
        KnowledgeDocument.filename == EVAL_DOCUMENT_NAME,
    )
    doc_res = await session.execute(doc_stmt)
    doc = doc_res.scalar_one_or_none()

    if doc is None or doc.status != KnowledgeStatus.COMPLETED:
        if doc is not None:
            # Delete stale document
            await session.delete(doc)
            await session.commit()

        logger.info(f"Ingesting evaluation PDF '{EVAL_DOCUMENT_NAME}' into knowledge {knowledge.id}")
        pdf_bytes = generate_test_pdf([PAGE_1_STRATEGY, PAGE_2_FACTORY])
        doc = await service.ingest_document(
            knowledge_id=knowledge.id,
            filename=EVAL_DOCUMENT_NAME,
            content=pdf_bytes,
            db=session,
        )
        logger.info(f"Ingested evaluation document {doc.id} with status {doc.status}")

    return knowledge


def evaluate_case(case: dict[str, Any], response: AnalysisResponse, duration_s: float) -> dict[str, Any]:
    """Evaluate grounding, citations, and reasoning criteria for an analysis response."""
    checks = case.get("checks", {})
    results: list[dict[str, Any]] = []
    failures: list[str] = []

    answer_text = response.answer.strip()
    sources = response.sources

    repo_sources = [s for s in sources if s.type == "repository"]
    knowledge_sources = [s for s in sources if s.type == "knowledge"]

    # Check 1: Answer not empty
    has_answer = len(answer_text) >= 20
    results.append({
        "check": "answer_length",
        "passed": has_answer,
        "detail": f"{len(answer_text)} chars",
    })
    if not has_answer:
        failures.append("Answer was empty or too short (< 20 chars)")

    # Check 2: Repository sources presence
    if "min_repo_sources" in checks:
        min_repo = checks["min_repo_sources"]
        passed = len(repo_sources) >= min_repo
        results.append({
            "check": "min_repo_sources",
            "passed": passed,
            "detail": f"{len(repo_sources)} repo sources (required >= {min_repo})",
        })
        if not passed:
            failures.append(f"Expected at least {min_repo} repository sources, got {len(repo_sources)}")

    # Check 3: Repository source files
    if "expected_repo_files" in checks:
        expected_files = checks["expected_repo_files"]
        actual_labels = [s.label for s in repo_sources]
        matched = any(
            any(exp in label for exp in expected_files)
            for label in actual_labels
        )
        results.append({
            "check": "expected_repo_files",
            "passed": matched,
            "detail": f"Labels: {actual_labels} matching {expected_files}",
        })
        if not matched:
            failures.append(f"Repository sources did not match expected files: {expected_files}")

    # Check 4: Knowledge sources presence
    if "min_knowledge_sources" in checks:
        min_k = checks["min_knowledge_sources"]
        passed = len(knowledge_sources) >= min_k
        results.append({
            "check": "min_knowledge_sources",
            "passed": passed,
            "detail": f"{len(knowledge_sources)} knowledge sources (required >= {min_k})",
        })
        if not passed:
            failures.append(f"Expected at least {min_k} knowledge sources, got {len(knowledge_sources)}")

    # Check 5: Expected terms in answer
    if "expected_knowledge_terms" in checks:
        expected_terms = checks["expected_knowledge_terms"]
        lower_ans = answer_text.lower()
        matched_terms = [t for t in expected_terms if t in lower_ans]
        passed = len(matched_terms) > 0
        results.append({
            "check": "expected_knowledge_terms",
            "passed": passed,
            "detail": f"Matched terms: {matched_terms} of {expected_terms}",
        })
        if not passed:
            failures.append(f"Answer did not contain any expected terms from knowledge: {expected_terms}")

    # Check 6: Insufficient knowledge refusal acknowledgement
    if checks.get("insufficient_knowledge_expected", False):
        refusal_phrases = checks.get("refusal_phrases", [])
        lower_ans = answer_text.lower()
        acknowledged = any(phrase in lower_ans for phrase in refusal_phrases)
        results.append({
            "check": "insufficient_knowledge_acknowledged",
            "passed": acknowledged,
            "detail": f"Limitation acknowledgement detected: {acknowledged}",
        })
        if not acknowledged:
            failures.append("Model failed to acknowledge insufficient knowledge for unsupported topic")

        # Verify no hallucinated citations claiming CQRS/Saga in knowledge document
        fake_citations = [s for s in knowledge_sources if "cqrs" in s.label.lower() or "saga" in s.label.lower()]
        passed_citations = len(fake_citations) == 0
        results.append({
            "check": "no_fabricated_knowledge_citations",
            "passed": passed_citations,
            "detail": f"Fabricated knowledge citations: {len(fake_citations)}",
        })
        if not passed_citations:
            failures.append("Found fabricated knowledge citations in response")

    passed_all = len(failures) == 0
    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "question": case["question"],
        "passed": passed_all,
        "failures": failures,
        "checks": results,
        "duration_s": round(duration_s, 2),
        "repository_sources": [
            {"source_id": s.source_id, "label": s.label}
            for s in repo_sources
        ],
        "knowledge_sources": [
            {"source_id": s.source_id, "label": s.label}
            for s in knowledge_sources
        ],
        "citations_count": len(sources),
        "answer": answer_text,
    }


async def run_evaluation(repository_id: UUID | None = None) -> int:
    """Run real Ollama behavioral evaluation for knowledge-guided analysis."""
    async with AsyncSessionLocal() as session:
        # Resolve target repository
        target_repo: Repository | None = None
        if repository_id:
            res = await session.execute(
                select(Repository).where(
                    Repository.id == repository_id,
                    Repository.status == IngestionStatus.COMPLETED,
                )
            )
            target_repo = res.scalar_one_or_none()
        else:
            # Prefer forge-ai repository if indexed, else Portfolio or first completed
            pref_ids = [
                UUID("fcbbe1db-7f95-45b1-8adc-339347486b83"),  # forge-ai
                UUID("8962366c-b33a-49d9-a4e0-919384c6665b"),  # Portfolio
            ]
            for pid in pref_ids:
                res = await session.execute(
                    select(Repository).where(
                        Repository.id == pid,
                        Repository.status == IngestionStatus.COMPLETED,
                    )
                )
                target_repo = res.scalar_one_or_none()
                if target_repo:
                    break

            if not target_repo:
                res = await session.execute(
                    select(Repository).where(Repository.status == IngestionStatus.COMPLETED).limit(1)
                )
                target_repo = res.scalar_one_or_none()

        if not target_repo:
            logger.error("No completed indexed repository found in database.")
            return 1

        # Ensure evaluation knowledge scope and document exist
        knowledge = await ensure_eval_knowledge(session)

        logger.info(f"Target repository: {target_repo.name} ({target_repo.id})")
        logger.info(f"Engineering knowledge scope: {knowledge.name} ({knowledge.id})")
        logger.info(f"LLM Provider: Ollama model={settings.ollama_model} base_url={settings.ollama_base_url}")

        llm_service = OllamaLLMService()
        analysis_service = KnowledgeGuidedAnalysisService(llm_service=llm_service)

        evaluation_results: list[dict[str, Any]] = []
        all_passed = True

        print("\n" + "=" * 80)
        print("  ForgeAI Knowledge-Guided Analysis Behavioral Evaluation (Real Ollama)")
        print(f"  Model: {settings.ollama_model} | Repo: {target_repo.name}")
        print(f"  Knowledge Scope: {knowledge.name}")
        print("=" * 80 + "\n")

        for idx, case in enumerate(EVALUATION_CASES, start=1):
            print(f"[{idx}/{len(EVALUATION_CASES)}] {case['name']} ({case['id']})")
            print(f"     Question: \"{case['question']}\"")

            code_scope = CodeScope(
                type=CodeScopeType(case["code_scope"]["type"]),
                path=case["code_scope"].get("path"),
            )

            start_t = time.perf_counter()
            try:
                response = await analysis_service.analyze(
                    repository_id=target_repo.id,
                    knowledge_id=knowledge.id,
                    code_scope=code_scope,
                    question=case["question"],
                    db=session,
                )
                duration_s = time.perf_counter() - start_t

                eval_result = evaluate_case(case, response, duration_s)
                evaluation_results.append(eval_result)

                status_str = "PASS" if eval_result["passed"] else "FAIL"
                if not eval_result["passed"]:
                    all_passed = False

                print(f"     Duration: {duration_s:.2f}s | Result: {status_str}")
                print(f"     Repo Sources:      {[s['label'] for s in eval_result['repository_sources']]}")
                print(f"     Knowledge Sources: {[s['label'] for s in eval_result['knowledge_sources']]}")
                print(f"     Answer (preview):  {eval_result['answer'][:180]}...")
                if eval_result["failures"]:
                    print(f"     Failures:          {eval_result['failures']}")
                print()

            except Exception as e:
                duration_s = time.perf_counter() - start_t
                all_passed = False
                logger.exception(f"Error running case {case['id']}: {e}")
                evaluation_results.append({
                    "case_id": case["id"],
                    "case_name": case["name"],
                    "question": case["question"],
                    "passed": False,
                    "failures": [f"Exception: {str(e)}"],
                    "checks": [],
                    "duration_s": round(duration_s, 2),
                    "repository_sources": [],
                    "knowledge_sources": [],
                    "citations_count": 0,
                    "answer": f"ERROR: {str(e)}",
                })

        # Save machine-readable evaluation report
        results_dir = Path(__file__).resolve().parent / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = results_dir / f"knowledge_eval_{timestamp}.json"
        latest_path = results_dir / "latest_knowledge.json"

        report_data = {
            "timestamp": datetime.now().isoformat(),
            "repository_id": str(target_repo.id),
            "repository_name": target_repo.name,
            "knowledge_id": str(knowledge.id),
            "knowledge_name": knowledge.name,
            "llm_provider": "ollama",
            "model": settings.ollama_model,
            "all_passed": all_passed,
            "total_cases": len(EVALUATION_CASES),
            "passed_cases": sum(1 for r in evaluation_results if r["passed"]),
            "cases": evaluation_results,
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        print("-" * 80)
        summary = (
            f"Evaluation Summary: {report_data['passed_cases']}/{report_data['total_cases']} cases passed. "
            f"Overall: {'PASSED' if all_passed else 'FAILED'}"
        )
        print(summary)
        print(f"Report saved to: {report_path.name}")
        print("=" * 80 + "\n")

        return 0 if all_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="ForgeAI Knowledge-Guided Analysis Evaluation Runner")
    parser.add_argument("--repository-id", type=UUID, default=None, help="Target repository UUID")
    args = parser.parse_args()

    sys.exit(asyncio.run(run_evaluation(args.repository_id)))


if __name__ == "__main__":
    main()
