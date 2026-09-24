"""
Agent orchestration service coordinating bounded repository investigation.
"""

import json
import logging
from pathlib import Path
import re
from typing import Any
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository
from app.schemas.agent import (
    AgentLLMResponse,
    AgentMessage,
    AgentMessageRole,
    AgentResponse,
    AgentStatus,
    AgentToolDefinition,
    ListFilesArgs,
    ReadFileArgs,
    SearchCodeArgs,
    SourceCitation,
    ToolCall,
    ToolName,
    get_agent_tool_definitions,
)
from app.services.agent_llm import AgentLLMService, MockAgentLLMService, get_agent_llm_service
from app.services.agent_prompt_builder import AgentPromptBuilder
from app.services.agent_state import AgentState
from app.services.agent_tools import AgentTools, ToolExecutionError
from app.services.retrieval import (
    RepositoryNotFoundError,
    RepositoryNotReadyForSearchError,
)

logger = logging.getLogger(__name__)


class AgentService:
    """Orchestrates bounded, read-only repository investigations."""

    def __init__(
        self,
        agent_tools: AgentTools | None = None,
        prompt_builder: AgentPromptBuilder | None = None,
        llm_service: AgentLLMService | None = None,
        max_iterations: int | None = None,
        max_tool_calls: int | None = None,
    ) -> None:
        self.tools = agent_tools or AgentTools()
        self.prompt_builder = prompt_builder or AgentPromptBuilder()
        self.llm = llm_service or get_agent_llm_service()
        self.max_iterations = max_iterations or settings.agent_max_iterations
        self.max_tool_calls = max_tool_calls or settings.agent_max_tool_calls
        self.max_grounding_retries = 2
        self.tool_definitions = get_agent_tool_definitions()

    @staticmethod
    def _is_repository_question(question: str) -> bool:
        """Determine if a question asks about repository code, structure, or behavior."""
        repo_keywords = {
            "repo", "repository", "code", "file", "files", "directory", "directories",
            "folder", "folders", "function", "functions", "class", "classes",
            "method", "methods", "module", "modules", "package", "packages",
            "implementation", "architecture", "purpose", "structure", "component",
            "components", "config", "configuration", "dependency", "dependencies",
            "workflow", "workflows", "readme", "test", "tests", "endpoint", "endpoints",
            "service", "services", "auth", "authentication", "database", "model", "models",
            "search", "find", "inspect", "cite", "explain", "main", "areas", "covers",
        }
        lowered = question.lower()
        words = set(re.findall(r"\b\w+\b", lowered))
        if words & repo_keywords:
            return True
        key_phrases = (
            "how does", "what does", "where is", "where are", "purpose of",
            "what is in", "what are the", "identify the", "show me",
        )
        return any(phrase in lowered for phrase in key_phrases)

    @staticmethod
    def _is_recoverable_path_error(error_msg: str) -> bool:
        """Determine whether a tool failure is a recoverable path/file resolution error."""
        lowered = error_msg.lower()
        return any(
            cue in lowered
            for cue in (
                "not found",
                "no such file",
                "does not exist",
                "not a regular file",
                "not a directory",
                "forbidden",
            )
        )

    async def validate_repository_readiness(
        self,
        repository_id: UUID,
        db: AsyncSession,
    ) -> Repository:
        """Verify repository existence, ingestion completion, local files, and indexed chunks."""
        repo = await db.get(Repository, repository_id)
        if repo is None:
            raise RepositoryNotFoundError(f"Repository with ID '{repository_id}' not found.")

        if repo.status != IngestionStatus.COMPLETED:
            raise RepositoryNotReadyForSearchError(
                f"Repository ingestion status is '{repo.status.value}'. "
                "Ingestion must be completed before starting an agent investigation."
            )

        # Verify cloned directory exists locally
        storage_root = self.tools.storage_root
        repo_dir = (storage_root / str(repository_id)).resolve()
        if not repo_dir.is_dir() or not repo_dir.is_relative_to(storage_root):
            raise RepositoryNotReadyForSearchError(
                "Cloned repository files are not available on the server. Please re-ingest."
            )

        # Verify actual database index readiness (chunks > 0)
        chunks_count = (
            await db.execute(
                select(func.count())
                .select_from(CodeChunk)
                .join(CodeFile, CodeChunk.file_id == CodeFile.id)
                .where(CodeFile.repository_id == repository_id)
            )
        ).scalar_one()

        if chunks_count == 0:
            raise RepositoryNotReadyForSearchError(
                "Repository has no indexed code chunks. Indexing must be completed before starting an agent run."
            )

        return repo

    async def run(
        self,
        repository_id: UUID,
        question: str,
        db: AsyncSession,
        max_iterations: int | None = None,
    ) -> AgentResponse:
        """Run bounded iterative investigation to answer a repository question."""
        await self.validate_repository_readiness(repository_id=repository_id, db=db)

        limit_iterations = max_iterations or self.max_iterations
        state = AgentState(
            repository_id=repository_id,
            question=question,
            max_iterations=limit_iterations,
            max_tool_calls=self.max_tool_calls,
        )

        messages: list[AgentMessage] = [
            AgentMessage(
                role=AgentMessageRole.SYSTEM,
                content=self.prompt_builder.SYSTEM_INSTRUCTIONS,
            ),
            AgentMessage(
                role=AgentMessageRole.USER,
                content=question.strip(),
            ),
        ]

        candidate_source_ids: list[str] = []

        while state.status == AgentStatus.RUNNING:
            # 1. Check stopping conditions
            if state.iteration >= state.max_iterations:
                state.status = AgentStatus.MAX_ITERATIONS
                break

            if state.tool_call_count >= state.max_tool_calls:
                state.status = AgentStatus.MAX_TOOL_CALLS
                break

            # 2. Invoke LLM with normalized messages & tool definitions
            try:
                llm_response = await self.llm.generate(
                    messages=messages,
                    tools=self.tool_definitions,
                )
            except Exception as exc:
                logger.warning("Agent LLM error at iteration %d: %s", state.iteration, exc)
                state.record_observation(
                    tool=ToolName.SEARCH_CODE,
                    arguments={},
                    success=False,
                    data=None,
                    error=f"LLM generation failed: {exc}",
                )
                state.iteration += 1
                continue

            # 3. Handle Tool Calls
            if llm_response.tool_calls:
                tool_msg_parts: list[AgentMessage] = []
                for tool_call in llm_response.tool_calls:
                    if state.tool_call_count >= state.max_tool_calls:
                        state.status = AgentStatus.MAX_TOOL_CALLS
                        break

                    state.tool_call_count += 1

                    # Execute tool safely
                    await self._execute_tool(
                        state=state,
                        tool=tool_call.tool,
                        arguments=tool_call.arguments,
                        db=db,
                    )

                    last_obs = state.observations[-1] if state.observations else {}
                    if last_obs.get("success"):
                        obs_payload = json.dumps(last_obs.get("data", {}))
                    else:
                        err_dict: dict[str, Any] = {"error": last_obs.get("error", "Tool execution failed")}
                        obs_data = last_obs.get("data")
                        if isinstance(obs_data, dict) and obs_data.get("recovery_guidance"):
                            err_dict["recovery_guidance"] = obs_data["recovery_guidance"]
                        obs_payload = json.dumps(err_dict)

                    tool_msg_parts.append(
                        AgentMessage(
                            role=AgentMessageRole.TOOL,
                            tool_name=tool_call.tool.value,
                            content=obs_payload,
                        )
                    )

                messages.append(
                    AgentMessage(
                        role=AgentMessageRole.ASSISTANT,
                        tool_calls=llm_response.tool_calls,
                        content=llm_response.final_text,
                    )
                )
                messages.extend(tool_msg_parts)
                state.iteration += 1

                if state.status != AgentStatus.RUNNING:
                    break
                continue

            # 4. Handle Final Answer
            if llm_response.final_text:
                has_verified_sources = len(state.source_registry.get_citations()) > 0
                is_repo_query = self._is_repository_question(question) or state.tool_call_count > 0

                # Check if content tools were attempted and model honestly reports lack of evidence
                has_attempted_content_tools = any(
                    obs.get("tool") in (ToolName.READ_FILE.value, ToolName.SEARCH_CODE.value)
                    for obs in state.observations
                )
                lower_final = llm_response.final_text.lower()
                is_insufficient_evidence_report = any(
                    phrase in lower_final
                    for phrase in (
                        "insufficient",
                        "no content",
                        "not found",
                        "cannot find",
                        "could not find",
                        "unable to find",
                        "does not contain",
                        "no evidence",
                        "no readable files",
                        "empty repository",
                    )
                )

                # Grounding safeguard: If repository-specific question has 0 verified sources
                # and model did not report insufficient evidence after attempting tools:
                if (
                    is_repo_query
                    and not has_verified_sources
                    and not (has_attempted_content_tools and is_insufficient_evidence_report)
                    and state.grounding_retries < self.max_grounding_retries
                    and state.iteration < state.max_iterations - 1
                ):
                    state.grounding_retries += 1
                    logger.info(
                        "Grounding safeguard triggered at iteration %d for repository question with 0 sources.",
                        state.iteration,
                    )

                    messages.append(
                        AgentMessage(
                            role=AgentMessageRole.ASSISTANT,
                            content=llm_response.final_text,
                        )
                    )
                    messages.append(
                        AgentMessage(
                            role=AgentMessageRole.USER,
                            content=(
                                "GROUNDING REQUIREMENT NOT MET.\n\n"
                                "You have not inspected any repository file contents yet.\n\n"
                                "For this repository-specific question, your next response MUST perform "
                                "a repository investigation using either `read_file` or `search_code`.\n\n"
                                "Do not provide a final answer yet.\n"
                                "Do not apologize or explain what you will do.\n"
                                "Do not output a natural-language preamble.\n\n"
                                "Your next response must be a tool call."
                            ),
                        )
                    )
                    state.record_observation(
                        tool=ToolName.READ_FILE,
                        arguments={},
                        success=False,
                        data=None,
                        error=(
                            "Grounding safeguard: Final answer rejected because no repository file contents "
                            "were inspected. Your next response must be a tool call using read_file or search_code."
                        ),
                    )
                    state.iteration += 1
                    continue

                state.final_answer = llm_response.final_text
                sids_in_text = re.findall(r"\b(src_\d+)\b", llm_response.final_text, re.IGNORECASE)
                candidate_source_ids = list(dict.fromkeys(sids_in_text))
                state.status = AgentStatus.COMPLETED
                state.iteration += 1
                break

            # 5. Empty Response
            state.record_observation(
                tool=ToolName.SEARCH_CODE,
                arguments={},
                success=False,
                data=None,
                error="Model produced empty response (no tool calls and no final text).",
            )
            state.iteration += 1

        # 6. Fallback final answer if stopping conditions were met without final decision
        if not state.final_answer:
            observed_count = len(state.source_registry.get_citations())
            state.final_answer = (
                f"[AGENT {state.status.value.upper()}] The agent concluded its investigation upon reaching "
                f"the configured boundary ({state.status.value}). Observed {observed_count} relevant source snippets."
            )

        # 7. Authoritative Programmatic Citations (Stable Source IDs)
        resolved_citations: list[SourceCitation] = []
        if candidate_source_ids:
            resolved_citations = state.source_registry.resolve_source_ids(candidate_source_ids)

        # If model didn't cite explicit src_X tags, check if model mentioned specific file paths in its answer
        if not resolved_citations and state.final_answer:
            all_sources = state.source_registry.get_citations()
            matching_sources = [
                s for s in all_sources
                if (s.path in state.final_answer or Path(s.path).name in state.final_answer)
            ]
            if matching_sources:
                resolved_citations = matching_sources

        # Fallback to all sources registered during the run if no specific citation could be resolved
        if not resolved_citations:
            resolved_citations = state.source_registry.get_citations()

        return AgentResponse(
            answer=state.final_answer,
            sources=resolved_citations,
            status=state.status,
            tool_calls_count=state.tool_call_count,
            iterations_count=state.iteration,
            tool_activity=state.tool_activity,
        )

    async def _execute_tool(
        self,
        state: AgentState,
        tool: ToolName,
        arguments: dict[str, Any],
        db: AsyncSession,
    ) -> None:
        """Validate arguments and safely execute the requested tool, recording observations and activity."""
        try:
            if tool == ToolName.SEARCH_CODE:
                args = SearchCodeArgs(**arguments)
                results = await self.tools.search_code(
                    repository_id=state.repository_id,
                    query=args.query,
                    db=db,
                    top_k=args.top_k,
                )

                observed_chunks: list[dict[str, Any]] = []
                for res in results:
                    source_id = state.source_registry.register(
                        path=res.path,
                        start_line=res.start_line,
                        end_line=res.end_line,
                        source_type="search",
                    )
                    observed_chunks.append({
                        "source_id": source_id,
                        "path": res.path,
                        "start_line": res.start_line,
                        "end_line": res.end_line,
                        "similarity": round(res.similarity, 4),
                        "snippet": res.content[:200] + ("..." if len(res.content) > 200 else ""),
                    })

                state.record_activity(
                    tool=tool,
                    parameters={"query": args.query, "top_k": args.top_k},
                    success=True,
                    summary=f"Found {len(results)} matching code chunks.",
                )
                state.record_observation(
                    tool=tool,
                    arguments=arguments,
                    success=True,
                    data={"count": len(results), "chunks": observed_chunks},
                )

            elif tool == ToolName.READ_FILE:
                args = ReadFileArgs(**arguments)
                read_res = self.tools.read_file(
                    repository_id=state.repository_id,
                    path=args.path,
                    start_line=args.start_line,
                    end_line=args.end_line,
                )

                source_id = state.source_registry.register(
                    path=read_res.path,
                    start_line=read_res.start_line,
                    end_line=read_res.end_line,
                    source_type="read",
                )

                state.record_activity(
                    tool=tool,
                    parameters={"path": args.path, "lines": f"{read_res.start_line}-{read_res.end_line}"},
                    success=True,
                    summary=f"Read {read_res.end_line - read_res.start_line + 1} lines from {read_res.path}.",
                )
                state.record_observation(
                    tool=tool,
                    arguments=arguments,
                    success=True,
                    data={
                        "source_id": source_id,
                        "path": read_res.path,
                        "start_line": read_res.start_line,
                        "end_line": read_res.end_line,
                        "content": read_res.content,
                    },
                )

            elif tool == ToolName.LIST_FILES:
                args = ListFilesArgs(**arguments)
                list_res = self.tools.list_files(
                    repository_id=state.repository_id,
                    path=args.path,
                    max_files=args.max_files,
                )

                state.record_activity(
                    tool=tool,
                    parameters={"path": args.path or "."},
                    success=True,
                    summary=f"Listed {len(list_res.entries)} entries (total found: {list_res.total_found}).",
                )
                state.record_observation(
                    tool=tool,
                    arguments=arguments,
                    success=True,
                    data={
                        "base_path": list_res.base_path,
                        "entries": list_res.entries,
                        "truncated": list_res.truncated,
                    },
                )

        except (ValidationError, ToolExecutionError) as err:
            err_msg = str(err)
            logger.info("Tool %s execution controlled error: %s", tool.value, err_msg)
            state.record_activity(
                tool=tool,
                parameters=arguments,
                success=False,
                summary=f"Tool failed: {err_msg}",
            )
            recovery_guidance = None
            if self._is_recoverable_path_error(err_msg):
                recovery_guidance = (
                    "The requested path was not found. This does NOT mean the requested information is "
                    "unavailable in the repository. Do not invent filenames blindly or conclude evidence is "
                    "unavailable. Use 'list_files' to discover directory contents or 'search_code' to search "
                    "for relevant keywords and locate the correct file path."
                )

            state.record_observation(
                tool=tool,
                arguments=arguments,
                success=False,
                data={"recovery_guidance": recovery_guidance} if recovery_guidance else None,
                error=err_msg,
            )
        except Exception as exc:
            logger.exception("Unexpected error executing tool %s: %s", tool.value, exc)
            state.record_activity(
                tool=tool,
                parameters=arguments,
                success=False,
                summary="Unexpected tool error.",
            )
            state.record_observation(
                tool=tool,
                arguments=arguments,
                success=False,
                data=None,
                error="An unexpected internal error occurred while executing this tool.",
            )


def get_default_agent_service() -> AgentService:
    """Factory to provide the default AgentService."""
    return AgentService(llm_service=get_agent_llm_service())
