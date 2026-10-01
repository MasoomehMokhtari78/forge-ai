"""
Retrieval Quality and Metrics Evaluation Runner for ForgeAI.

Evaluates hybrid retrieval against the active indexed repository in PostgreSQL,
measuring Precision@K, Recall@K, and Mean Reciprocal Rank (MRR) across representative queries.
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

from app.core.database import AsyncSessionLocal
from app.models.repository import IngestionStatus, Repository
from app.services.retrieval import RetrievalService
from app.services.retrieval_metrics import (
    mean_reciprocal_rank,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("retrieval_eval")

BENCHMARK_CASES: list[dict[str, Any]] = [
    {
        "id": "case-1-projects",
        "name": "Projects Section Implementation",
        "query": "Where is the projects section handled or rendered?",
        "relevant_files": ["app/page.tsx", "components/Projects/Projects.tsx"],
        "noise_files": ["package-lock.json", "components.json"],
    },
    {
        "id": "case-2-styles-fonts",
        "name": "Global Styles and Fonts Configuration",
        "query": "Where are global styles and fonts configured?",
        "relevant_files": ["app/layout.tsx", "app/globals.css"],
        "noise_files": ["package-lock.json"],
    },
    {
        "id": "case-3-identifier",
        "name": "Code Identifier Discovery (CardSpotlight)",
        "query": "Where is CardSpotlight implemented?",
        "relevant_files": ["components/ui/card-spotlight.tsx"],
        "noise_files": [],
    },
    {
        "id": "case-4-semantic",
        "name": "Semantic Concept (Personal Background / Developer Introduction)",
        "query": "Where does the developer introduce herself?",
        "relevant_files": ["app/page.tsx", "components/Introduction/Introduction.tsx"],
        "noise_files": ["package-lock.json", "components.json"],
    },
]


async def run_evaluation(repository_id: UUID | None = None) -> int:
    """Run retrieval benchmark against target repository."""
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
            logger.error("No completed indexed repository found in database.")
            return 1

        logger.info(f"Target repository: {target_repo.name} ({target_repo.id})")

        retrieval_service = RetrievalService()
        evaluation_results: list[dict[str, Any]] = []
        metric_pairs: list[tuple[list[str], set[str]]] = []

        print("\n" + "=" * 80)
        print("  ForgeAI Hybrid Retrieval Evaluation (Semantic + Lexical + Path + RRF)")
        print("=" * 80 + "\n")

        for idx, case in enumerate(BENCHMARK_CASES, start=1):
            query = case["query"]
            relevant_set = set(case["relevant_files"])
            noise_set = set(case["noise_files"])

            results = await retrieval_service.search(
                repository_id=target_repo.id,
                query=query,
                db=session,
                top_k=5,
            )

            retrieved_paths = [r.path for r in results]
            metric_pairs.append((retrieved_paths, relevant_set))

            p3 = precision_at_k(retrieved_paths, relevant_set, k=3)
            r3 = recall_at_k(retrieved_paths, relevant_set, k=3)
            rr = reciprocal_rank(retrieved_paths, relevant_set)

            # Check noise suppression
            noise_in_top2 = any(p in noise_set for p in retrieved_paths[:2])

            case_passed = (rr == 1.0) and not noise_in_top2

            case_data = {
                "case_id": case["id"],
                "name": case["name"],
                "query": query,
                "passed": case_passed,
                "retrieved_paths": retrieved_paths,
                "precision_at_3": round(p3, 4),
                "recall_at_3": round(r3, 4),
                "reciprocal_rank": round(rr, 4),
                "noise_suppressed": not noise_in_top2,
            }
            evaluation_results.append(case_data)

            status_str = "PASSED" if case_passed else "FAILED"
            print(f"[{idx}/{len(BENCHMARK_CASES)}] {case['name']} -> {status_str}")
            print(f"     Query:       \"{query}\"")
            print(f"     Top-3 Files: {retrieved_paths[:3]}")
            print(f"     Metrics:     P@3: {p3:.2f} | R@3: {r3:.2f} | RR: {rr:.2f}")
            if noise_set:
                print(f"     Noise Check: noise in top-2: {noise_in_top2} (Noise: {list(noise_set)})")
            print()

        # Compute aggregate metrics
        mrr = mean_reciprocal_rank(metric_pairs)
        mean_p3 = sum(r["precision_at_3"] for r in evaluation_results) / len(evaluation_results)
        mean_r3 = sum(r["recall_at_3"] for r in evaluation_results) / len(evaluation_results)
        all_passed = all(r["passed"] for r in evaluation_results)

        results_dir = Path(__file__).resolve().parent / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = results_dir / f"retrieval_eval_{timestamp}.json"
        latest_path = results_dir / "latest_retrieval.json"

        report_data = {
            "timestamp": datetime.now().isoformat(),
            "repository_id": str(target_repo.id),
            "repository_name": target_repo.name,
            "all_passed": all_passed,
            "mean_reciprocal_rank": round(mrr, 4),
            "mean_precision_at_3": round(mean_p3, 4),
            "mean_recall_at_3": round(mean_r3, 4),
            "cases": evaluation_results,
        }

        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)
        with open(latest_path, "w", encoding="utf-8") as f:
            json.dump(report_data, f, indent=2)

        print("-" * 80)
        print(f"Overall Results: {'PASSED' if all_passed else 'FAILED'}")
        print(f"Mean Reciprocal Rank (MRR): {mrr:.4f}")
        print(f"Mean Precision@3:          {mean_p3:.4f}")
        print(f"Mean Recall@3:             {mean_r3:.4f}")
        print(f"Report saved to: {report_path.relative_to(Path.cwd() if Path.cwd() in report_path.parents else Path('.'))}")
        print("=" * 80 + "\n")

        return 0 if all_passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="ForgeAI Retrieval Quality Evaluation Runner")
    parser.add_argument("--repository-id", type=UUID, default=None, help="Target repository UUID")
    args = parser.parse_args()

    sys.exit(asyncio.run(run_evaluation(args.repository_id)))


if __name__ == "__main__":
    main()
