"""
Repeatable Agent Evaluation Harness for ForgeAI.

Executes evaluation cases against real AgentService and real Ollama local LLM,
recording execution trajectory, sources, citations, and deterministic behavioral check results.
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
from app.schemas.agent import AgentResponse, AgentStatus
from app.services.agent import AgentService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("agent_eval")


def evaluate_checks(case: dict[str, Any], response: AgentResponse) -> dict[str, Any]:
    """Apply deterministic evaluation checks to an AgentResponse."""
    checks_def = case.get("checks", {})
    check_results: list[dict[str, Any]] = []
    failures: list[str] = []

    # 1. must_be_completed
    if "must_be_completed" in checks_def:
        expected = checks_def["must_be_completed"]
        actual_is_completed = (response.status == AgentStatus.COMPLETED)
        passed = (actual_is_completed == expected)
        desc = f"must_be_completed: status is '{response.status.value}'"
        check_results.append({"name": "must_be_completed", "passed": passed, "detail": desc})
        if not passed:
            failures.append(f"Expected status completed={expected}, but got '{response.status.value}'")

    # 2. min_sources
    if "min_sources" in checks_def:
        min_src = checks_def["min_sources"]
        actual_src = len(response.sources)
        passed = actual_src >= min_src
        desc = f"min_sources: {actual_src} source(s) (required >= {min_src})"
        check_results.append({"name": "min_sources", "passed": passed, "detail": desc})
        if not passed:
            failures.append(f"Expected at least {min_src} source(s), but got {actual_src}")

    # 3. max_sources
    if "max_sources" in checks_def:
        max_src = checks_def["max_sources"]
        actual_src = len(response.sources)
        passed = actual_src <= max_src
        desc = f"max_sources: {actual_src} source(s) (allowed <= {max_src})"
        check_results.append({"name": "max_sources", "passed": passed, "detail": desc})
        if not passed:
            failures.append(f"Expected at most {max_src} source(s), but got {actual_src}")

    # 4. min_tool_calls
    if "min_tool_calls" in checks_def:
        min_tc = checks_def["min_tool_calls"]
        actual_tc = response.tool_calls_count
        passed = actual_tc >= min_tc
        desc = f"min_tool_calls: {actual_tc} tool call(s) (required >= {min_tc})"
        check_results.append({"name": "min_tool_calls", "passed": passed, "detail": desc})
        if not passed:
            failures.append(f"Expected at least {min_tc} tool call(s), but got {actual_tc}")

    # 5. max_tool_calls
    if "max_tool_calls" in checks_def:
        max_tc = checks_def["max_tool_calls"]
        actual_tc = response.tool_calls_count
        passed = actual_tc <= max_tc
        desc = f"max_tool_calls: {actual_tc} tool call(s) (allowed <= {max_tc})"
        check_results.append({"name": "max_tool_calls", "passed": passed, "detail": desc})
        if not passed:
            failures.append(f"Expected at most {max_tc} tool call(s), but got {actual_tc}")

    # 6. required_tools
    if "required_tools" in checks_def:
        req_tools = checks_def["required_tools"]
        used_tools = {act.tool.value for act in response.tool_activity}
        for req in req_tools:
            passed = req in used_tools
            desc = f"required_tool '{req}': {'used' if passed else 'NOT used'}"
            check_results.append({"name": f"required_tool_{req}", "passed": passed, "detail": desc})
            if not passed:
                failures.append(f"Required tool '{req}' was not used during investigation")

    # 7. forbidden_tools
    if "forbidden_tools" in checks_def:
        forb_tools = checks_def["forbidden_tools"]
        used_tools = {act.tool.value for act in response.tool_activity}
        for forb in forb_tools:
            passed = forb not in used_tools
            desc = f"forbidden_tool '{forb}': {'NOT used' if passed else 'WAS used'}"
            check_results.append({"name": f"forbidden_tool_{forb}", "passed": passed, "detail": desc})
            if not passed:
                failures.append(f"Forbidden tool '{forb}' was used during investigation")

    # 8. answer_contains
    if "answer_contains" in checks_def:
        phrases = checks_def["answer_contains"]
        ans_lower = response.answer.lower()
        for phrase in phrases:
            passed = phrase.lower() in ans_lower
            desc = f"answer_contains '{phrase}': {'found' if passed else 'missing'}"
            check_results.append({"name": f"answer_contains_{phrase}", "passed": passed, "detail": desc})
            if not passed:
                failures.append(f"Answer missing expected keyword/phrase: '{phrase}'")

    # 9. answer_not_contains
    if "answer_not_contains" in checks_def:
        phrases = checks_def["answer_not_contains"]
        ans_lower = response.answer.lower()
        for phrase in phrases:
            passed = phrase.lower() not in ans_lower
            desc = f"answer_not_contains '{phrase}': {'absent' if passed else 'PRESENT'}"
            check_results.append({"name": f"answer_not_contains_{phrase}", "passed": passed, "detail": desc})
            if not passed:
                failures.append(f"Answer contained forbidden keyword/phrase: '{phrase}'")

    overall_passed = len(failures) == 0

    # Diagnostic reasoning summary for failure
    diagnosis = None
    if not overall_passed:
        used_tools = [act.tool.value for act in response.tool_activity]
        if response.status == AgentStatus.MAX_ITERATIONS:
            diagnosis = "Agent reached maximum iteration budget without completing or grounding the final answer."
        elif len(response.sources) == 0 and "read_file" not in used_tools and "search_code" not in used_tools:
            diagnosis = "Agent performed discovery (e.g. list_files) but failed to execute content tools (read_file / search_code)."
        elif len(response.sources) == 0:
            diagnosis = "Content tools were executed but no verified citations were produced in the SourceRegistry."
        else:
            diagnosis = f"Behavioral check failed: {'; '.join(failures)}"

    return {
        "passed": overall_passed,
        "check_results": check_results,
        "failures": failures,
        "diagnosis": diagnosis,
    }


def print_case_report(
    idx: int,
    total: int,
    case: dict[str, Any],
    response: AgentResponse,
    eval_result: dict[str, Any],
) -> None:
    """Print human-readable summary for a single evaluation case."""
    passed = eval_result["passed"]
    status_symbol = "[PASS]" if passed else "[FAIL]"

    print("\n" + "=" * 70)
    print(f"CASE [{idx}/{total}]: {case['id']} - {case.get('name', '')}")
    print("=" * 70)
    print(f"Question:\n{case['question']}\n")
    print(f"Result:\n{status_symbol}")
    print(f"Status: {response.status.value}")
    print(f"Iterations: {response.iterations_count}")
    print(f"Tool Calls: {response.tool_calls_count}")

    print("\nTool Trajectory:")
    if response.tool_activity:
        for act in response.tool_activity:
            params_str = json.dumps(act.parameters)
            print(f"  {act.execution_order}. {act.tool.value}")
            print(f"     parameters: {params_str}")
            print(f"     success: {act.success}")
            print(f"     summary: {act.summary}")
    else:
        print("  (No tools executed)")

    print(f"\nSources ({len(response.sources)}):")
    if response.sources:
        for src in response.sources:
            print(f"  [{src.source_id}] {src.path} (lines {src.start_line}-{src.end_line}) [{src.source_type}]")
    else:
        print("  (No verified sources citation registered)")

    print(f"\nAnswer:\n{response.answer}\n")

    passed_checks = sum(1 for c in eval_result["check_results"] if c["passed"])
    total_checks = len(eval_result["check_results"])
    print(f"Checks ({passed_checks}/{total_checks} passed):")
    for check in eval_result["check_results"]:
        mark = "[OK]" if check["passed"] else "[FAIL]"
        print(f"  {mark} {check['detail']}")

    if not passed:
        print("\nFailures:")
        for f in eval_result["failures"]:
            print(f"  [FAIL] {f}")
        if eval_result["diagnosis"]:
            print(f"\nLikely behavioral issue:\n  {eval_result['diagnosis']}")


async def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="ForgeAI Agent Evaluation Runner")
    parser.add_argument(
        "--repository-id",
        type=str,
        default=None,
        help="UUID of the ingested repository to evaluate against (defaults to first COMPLETED repo).",
    )
    parser.add_argument(
        "--cases",
        type=str,
        default="evals/cases.json",
        help="Path to evaluation cases JSON file (default: evals/cases.json).",
    )
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=8,
        help="Max iteration budget per evaluation run (default: 8).",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="evals/results",
        help="Directory to save machine-readable evaluation reports (default: evals/results).",
    )
    parser.add_argument(
        "--case-id",
        type=str,
        default=None,
        help="Optional single case ID to execute.",
    )
    args = parser.parse_args()

    # Load cases dataset
    cases_path = Path(args.cases)
    if not cases_path.is_absolute():
        # Resolve relative to backend root
        backend_dir = Path(__file__).resolve().parent.parent
        cases_path = backend_dir / args.cases

    if not cases_path.exists():
        print(f"Error: Evaluation cases file not found at {cases_path}")
        sys.exit(1)

    with open(cases_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    all_cases = dataset.get("cases", [])
    if args.case_id:
        all_cases = [c for c in all_cases if c["id"] == args.case_id]
        if not all_cases:
            print(f"Error: Case ID '{args.case_id}' not found in dataset.")
            sys.exit(1)

    # Initialize DB session and discover target repository
    async with AsyncSessionLocal() as db:
        if args.repository_id:
            try:
                repo_id = UUID(args.repository_id)
            except ValueError:
                print(f"Error: Invalid repository UUID format: '{args.repository_id}'")
                sys.exit(1)
            repo = await db.get(Repository, repo_id)
            if not repo:
                print(f"Error: Repository with ID '{repo_id}' not found in database.")
                sys.exit(1)
        else:
            stmt = select(Repository).where(Repository.status == IngestionStatus.COMPLETED).limit(1)
            res = await db.execute(stmt)
            repo = res.scalar_one_or_none()
            if not repo:
                print("Error: No ingested repository with status COMPLETED found in database.")
                sys.exit(1)

        print("\n" + "=" * 70)
        print("FORGEAI AGENT EVALUATION RUNNER")
        print("=" * 70)
        print(f"LLM Provider:     {settings.llm_provider.upper()}")
        print(f"Ollama Base URL:  {settings.ollama_base_url}")
        print(f"Ollama Model:     {settings.ollama_model}")
        print(f"Repository Name:  {repo.name}")
        print(f"Repository ID:    {repo.id}")
        print(f"Evaluation Cases: {len(all_cases)}")
        print(f"Max Iterations:   {args.max_iterations}")
        print("=" * 70 + "\n")

        # Initialize real AgentService
        agent_service = AgentService(max_iterations=args.max_iterations)

        case_results: list[dict[str, Any]] = []
        start_time = datetime.now()

        for idx, case in enumerate(all_cases, 1):
            logger.info("Starting evaluation case %d/%d: %s", idx, len(all_cases), case["id"])
            try:
                agent_resp = await agent_service.run(
                    repository_id=repo.id,
                    question=case["question"],
                    db=db,
                    max_iterations=args.max_iterations,
                )
            except Exception as exc:
                logger.error("Agent execution failed for case %s: %s", case["id"], exc, exc_info=True)
                agent_resp = AgentResponse(
                    answer=f"ERROR: Agent execution failed: {exc}",
                    sources=[],
                    status=AgentStatus.FAILED,
                    tool_calls_count=0,
                    iterations_count=0,
                    tool_activity=[],
                )

            eval_res = evaluate_checks(case, agent_resp)
            print_case_report(idx, len(all_cases), case, agent_resp, eval_res)

            case_record = {
                "id": case["id"],
                "name": case.get("name", case["id"]),
                "question": case["question"],
                "passed": eval_res["passed"],
                "status": agent_resp.status.value,
                "iterations_count": agent_resp.iterations_count,
                "tool_calls_count": agent_resp.tool_calls_count,
                "sources_count": len(agent_resp.sources),
                "answer": agent_resp.answer,
                "sources": [s.model_dump() for s in agent_resp.sources],
                "tool_activity": [act.model_dump() for act in agent_resp.tool_activity],
                "check_results": eval_res["check_results"],
                "failures": eval_res["failures"],
                "diagnosis": eval_res["diagnosis"],
            }
            case_results.append(case_record)

        end_time = datetime.now()
        duration_sec = (end_time - start_time).total_seconds()

        # Compute aggregate metrics
        total_cases = len(case_results)
        passed_cases = sum(1 for c in case_results if c["passed"])
        failed_cases = total_cases - passed_cases
        pass_rate = passed_cases / total_cases if total_cases > 0 else 0.0

        avg_iterations = sum(c["iterations_count"] for c in case_results) / total_cases if total_cases else 0.0
        avg_tool_calls = sum(c["tool_calls_count"] for c in case_results) / total_cases if total_cases else 0.0
        avg_sources = sum(c["sources_count"] for c in case_results) / total_cases if total_cases else 0.0

        completed_runs = sum(1 for c in case_results if c["status"] == AgentStatus.COMPLETED.value)
        max_iter_runs = sum(1 for c in case_results if c["status"] == AgentStatus.MAX_ITERATIONS.value)
        zero_source_runs = sum(1 for c in case_results if c["sources_count"] == 0)

        runs_using_search = sum(
            1 for c in case_results
            if any(act["tool"] == "search_code" for act in c["tool_activity"])
        )
        runs_using_read = sum(
            1 for c in case_results
            if any(act["tool"] == "read_file" for act in c["tool_activity"])
        )
        runs_using_list = sum(
            1 for c in case_results
            if any(act["tool"] == "list_files" for act in c["tool_activity"])
        )

        summary_metrics = {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "failed_cases": failed_cases,
            "pass_rate": round(pass_rate, 4),
            "pass_rate_percentage": f"{round(pass_rate * 100, 1)}%",
            "duration_seconds": round(duration_sec, 2),
            "avg_iterations": round(avg_iterations, 2),
            "avg_tool_calls": round(avg_tool_calls, 2),
            "avg_sources": round(avg_sources, 2),
            "completed_runs": completed_runs,
            "max_iteration_runs": max_iter_runs,
            "zero_source_runs": zero_source_runs,
            "runs_using_search_code": runs_using_search,
            "runs_using_read_file": runs_using_read,
            "runs_using_list_files": runs_using_list,
        }

        report_payload = {
            "metadata": {
                "timestamp": datetime.now().isoformat(),
                "llm_provider": settings.llm_provider,
                "ollama_base_url": settings.ollama_base_url,
                "ollama_model": settings.ollama_model,
                "repository_id": str(repo.id),
                "repository_name": repo.name,
                "max_iterations": args.max_iterations,
                "cases_file": str(cases_path),
            },
            "summary": summary_metrics,
            "cases": case_results,
        }

        # Save machine-readable evaluation reports
        out_dir = Path(args.output_dir)
        if not out_dir.is_absolute():
            backend_dir = Path(__file__).resolve().parent.parent
            out_dir = backend_dir / args.output_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = out_dir / f"agent_eval_{timestamp_str}.json"
        latest_file = out_dir / "latest.json"

        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report_payload, f, indent=2)

        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump(report_payload, f, indent=2)

        # Print overall summary to terminal
        print("\n" + "=" * 70)
        print("FORGEAI EVALUATION RUN SUMMARY")
        print("=" * 70)
        print(f"Total Cases Evaluated:   {total_cases}")
        print(f"Passed:                  {passed_cases}")
        print(f"Failed:                  {failed_cases}")
        print(f"Pass Rate:               {summary_metrics['pass_rate_percentage']}")
        print(f"Duration:                {summary_metrics['duration_seconds']}s")
        print("-" * 70)
        print(f"Average Iterations:      {summary_metrics['avg_iterations']}")
        print(f"Average Tool Calls:      {summary_metrics['avg_tool_calls']}")
        print(f"Average Verified Sources:{summary_metrics['avg_sources']}")
        print("-" * 70)
        print(f"Completed Runs:          {completed_runs}/{total_cases}")
        print(f"Max-Iteration Budget Runs:{max_iter_runs}/{total_cases}")
        print(f"Zero Source Runs:        {zero_source_runs}/{total_cases}")
        print("-" * 70)
        print(f"Runs Using list_files:   {runs_using_list}/{total_cases}")
        print(f"Runs Using read_file:    {runs_using_read}/{total_cases}")
        print(f"Runs Using search_code:  {runs_using_search}/{total_cases}")
        print("=" * 70)
        print(f"Saved machine-readable report to:\n  {report_file}\n  {latest_file}")
        print("=" * 70 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
