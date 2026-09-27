"""
Real LLM Behavioral Evaluation Suite for ForgeAI RAG Pipeline.

Executes repository questions against real pgvector retrieval, prompt/context building,
and the local Ollama LLM (qwen2.5-coder:7b), verifying:
- Relevant grounded answer generation
- Source citation accuracy and file presence
- Hallucination prevention (answers reflect retrieved evidence)
- Grounding refusal behavior on unsupported/out-of-domain queries
"""

import argparse
import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
import sys
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.repository import IngestionStatus, Repository
from app.schemas.rag import ChatRequest, ChatResponse
from app.services.llm import OllamaLLMService
from app.services.rag import RAGService
from app.services.retrieval import RetrievalService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("rag_eval")

# Evaluation cases for Portfolio repository (8962366c-b33a-49d9-a4e0-919384c6665b)
# or general repositories with Next.js/React structure
DEFAULT_RAG_CASES: list[dict[str, Any]] = [
    {
        "id": "rag-projects-section",
        "name": "Projects Section Implementation Discovery",
        "question": "Where is the projects section handled or rendered?",
        "checks": {
            "min_sources": 1,
            "expected_source_substrings": ["page.tsx", "projects"],
            "must_not_contain_hallucinations": True,
            "answer_min_length": 20,
        },
    },
    {
        "id": "rag-styling-fonts",
        "name": "Global Styling and Font Configuration",
        "question": "Where are global styles and fonts configured?",
        "checks": {
            "min_sources": 1,
            "expected_source_substrings": ["globals.css", "layout.tsx", "tailwind"],
            "must_not_contain_hallucinations": True,
            "answer_min_length": 20,
        },
    },
    {
        "id": "rag-grounding-refusal",
        "name": "Grounding Refusal on Unsupported Out-of-Domain Question",
        "question": "Explain the quantum entanglement algorithm and relativistic warp drive calculations in this codebase.",
        "checks": {
            "is_refusal_expected": True,
            "refusal_phrases": [
                "couldn't find enough relevant code",
                "not enough information",
                "does not contain",
                "unable to find",
            ],
            "max_sources": 0,
        },
    },
]


def evaluate_rag_case(case: dict[str, Any], response: ChatResponse) -> dict[str, Any]:
    """Evaluate deterministic and behavioral criteria for a RAG response."""
    checks = case.get("checks", {})
    results: list[dict[str, Any]] = []
    failures: list[str] = []

    answer_text = response.answer.strip()
    sources = response.sources

    # Check 1: Answer length
    if "answer_min_length" in checks:
        min_len = checks["answer_min_length"]
        passed = len(answer_text) >= min_len
        results.append({
            "check": "answer_min_length",
            "passed": passed,
            "detail": f"Length {len(answer_text)} (required >= {min_len})",
        })
        if not passed:
            failures.append(f"Answer too short ({len(answer_text)} chars)")

    # Check 2: Minimum sources
    if "min_sources" in checks:
        min_src = checks["min_sources"]
        passed = len(sources) >= min_src
        results.append({
            "check": "min_sources",
            "passed": passed,
            "detail": f"{len(sources)} source(s) (required >= {min_src})",
        })
        if not passed:
            failures.append(f"Expected at least {min_src} sources, got {len(sources)}")

    # Check 3: Maximum sources
    if "max_sources" in checks:
        max_src = checks["max_sources"]
        passed = len(sources) <= max_src
        results.append({
            "check": "max_sources",
            "passed": passed,
            "detail": f"{len(sources)} source(s) (allowed <= {max_src})",
        })
        if not passed:
            failures.append(f"Expected at most {max_src} sources, got {len(sources)}")

    # Check 4: Expected source file substrings
    if "expected_source_substrings" in checks:
        expected_subs = checks["expected_source_substrings"]
        source_paths = [s.file_path.lower() for s in sources]
        matched = any(
            any(sub.lower() in p for p in source_paths)
            for sub in expected_subs
        )
        results.append({
            "check": "expected_source_match",
            "passed": matched,
            "detail": f"Sources: {source_paths} matching any of {expected_subs}",
        })
        if not matched:
            failures.append(f"None of sources {source_paths} matched expected {expected_subs}")

    # Check 5: Grounding refusal on unsupported question
    if checks.get("is_refusal_expected", False):
        refusal_phrases = checks.get("refusal_phrases", ["couldn't find enough relevant code"])
        matched_refusal = any(phrase.lower() in answer_text.lower() for phrase in refusal_phrases)
        results.append({
            "check": "grounding_refusal",
            "passed": matched_refusal,
            "detail": f"Refusal detected: {matched_refusal}",
        })
        if not matched_refusal:
            failures.append(f"Expected grounding refusal in answer, but got: {answer_text[:100]}...")

    passed_all = len(failures) == 0
    return {
        "case_id": case["id"],
        "case_name": case["name"],
        "passed": passed_all,
        "failures": failures,
        "checks": results,
        "answer_preview": answer_text[:200] + ("..." if len(answer_text) > 200 else ""),
        "sources_count": len(sources),
        "source_files": [s.file_path for s in sources],
    }


async def run_evaluation(repository_id: UUID | None = None) -> int:
    """Run all RAG behavioral evaluation cases against real LLM."""
    async with AsyncSessionLocal() as session:
        # Determine target repository
        target_repo: Repository | None = None
        if repository_id:
            res = await session.execute(
                select(Repository).where(
                    Repository.id == repository_id,
                    Repository.status == IngestionStatus.COMPLETED,
                )
            )
            target_repo = res.scalar_one_or_none()
            if not target_repo:
                logger.error(f"Repository {repository_id} not found or not completed.")
                return 1
        else:
            # Prefer 8962366c-b33a-49d9-a4e0-919384c6665b (Portfolio) or first completed repo
            pref_id = UUID("8962366c-b33a-49d9-a4e0-919384c6665b")
            res = await session.execute(
                select(Repository).where(
                    Repository.id == pref_id,
                    Repository.status == IngestionStatus.COMPLETED,
                )
            )
            target_repo = res.scalar_one_or_none()
            if not target_repo:
                res = await session.execute(
                    select(Repository).where(Repository.status == IngestionStatus.COMPLETED).limit(1)
                )
                target_repo = res.scalar_one_or_none()

        if not target_repo:
            logger.error("No completed indexed repository found in database to evaluate.")
            return 1

        logger.info(f"Target repository: {target_repo.name} ({target_repo.id})")
        logger.info(f"Using LLM: Ollama qwen2.5-coder:7b at {settings.ollama_base_url}")

        retrieval_service = RetrievalService()
        llm_service = OllamaLLMService()
        rag_service = RAGService(retrieval_service=retrieval_service, llm_service=llm_service)

        evaluation_results: list[dict[str, Any]] = []
        all_passed = True

        print("\n" + "=" * 80)
        print("  ForgeAI RAG Behavioral Evaluation Suite (Real Ollama / Qwen2.5-Coder:7b)")
        print("=" * 80 + "\n")

        for idx, case in enumerate(DEFAULT_RAG_CASES, start=1):
            print(f"[{idx}/{len(DEFAULT_RAG_CASES)}] Running Case: {case['name']} ({case['id']})")
            print(f"     Question: \"{case['question']}\"")

            start_t = datetime.now()
            try:
                response = await rag_service.answer_question(
                    repository_id=target_repo.id,
                    question=case["question"],
                    db=session,
                )
                duration_s = (datetime.now() - start_t).total_seconds()

                eval_result = evaluate_rag_case(case, response)
                eval_result["duration_seconds"] = round(duration_s, 2)
                evaluation_results.append(eval_result)

                if eval_result["passed"]:
                    print(f"     Status:   PASSED ({duration_s:.1f}s)")
                    print(f"     Sources:  {len(response.sources)} cited -> {eval_result['source_files']}")
                    print(f"     Answer:   {eval_result['answer_preview']}\n")
                else:
                    all_passed = False
                    print(f"     Status:   FAILED ({duration_s:.1f}s)")
                    for failure in eval_result["failures"]:
                        print(f"       * Fail: {failure}")
                    print(f"     Answer:   {eval_result['answer_preview']}\n")

            except Exception as e:
                all_passed = False
                logger.exception(f"Error running case {case['id']}: {e}")
                evaluation_results.append({
                    "case_id": case["id"],
                    "case_name": case["name"],
                    "passed": False,
                    "failures": [f"Exception: {str(e)}"],
                    "checks": [],
                })

        # Save machine-readable evaluation report
        results_dir = Path(__file__).resolve().parent / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = results_dir / f"rag_eval_{timestamp}.json"
        latest_path = results_dir / "latest_rag.json"

        report_data = {
            "timestamp": datetime.now().isoformat(),
            "repository_id": str(target_repo.id),
            "repository_name": target_repo.name,
            "llm_provider": "ollama",
            "model": settings.ollama_model,
            "all_passed": all_passed,
            "total_cases": len(DEFAULT_RAG_CASES),
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
        print(f"Report saved to: {report_path.relative_to(Path.cwd() if Path.cwd() in report_path.parents else Path('.'))}")
        print("=" * 80 + "\n")

        return 0 if all_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="ForgeAI RAG Behavioral Evaluation Runner")
    parser.add_argument("--repository-id", type=UUID, default=None, help="Target repository UUID")
    args = parser.parse_args()

    sys.exit(asyncio.run(run_evaluation(args.repository_id)))


if __name__ == "__main__":
    main()
