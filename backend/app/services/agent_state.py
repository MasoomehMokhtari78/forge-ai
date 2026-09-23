"""
Agent state tracking and authoritative citation registry with stable source IDs.
"""

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.schemas.agent import AgentStatus, SourceCitation, ToolActivitySummary, ToolName


class SourceRegistry:
    """Authoritative in-memory registry of observed code snippets with stable source IDs.

    Guarantees:
      - Assigns deterministic, stable IDs (e.g. 'src_1', 'src_2') to observed snippets.
      - Only successfully observed content from read_file or search_code can enter.
      - Never trusts LLM-invented paths or line numbers.
    """

    def __init__(self) -> None:
        self._sources: dict[str, SourceCitation] = {}
        self._key_to_id: dict[tuple[str, int, int], str] = {}
        self._counter: int = 0

    def register(
        self,
        path: str,
        start_line: int,
        end_line: int,
        source_type: str,
    ) -> str:
        """Register an observed code snippet and return its stable source ID."""
        key = (path, start_line, end_line)
        if key in self._key_to_id:
            return self._key_to_id[key]

        self._counter += 1
        source_id = f"src_{self._counter}"
        citation = SourceCitation(
            source_id=source_id,
            path=path,
            start_line=start_line,
            end_line=end_line,
            source_type=source_type,
        )
        self._sources[source_id] = citation
        self._key_to_id[key] = source_id
        return source_id

    def get_citations(self) -> list[SourceCitation]:
        """Return all registered source citations in order of discovery."""
        return list(self._sources.values())

    def resolve_source_ids(self, source_ids: list[str]) -> list[SourceCitation]:
        """Resolve a list of candidate source IDs against the registry, filtering out invalid ones."""
        resolved: list[SourceCitation] = []
        for sid in source_ids:
            clean_id = sid.strip().lower()
            if clean_id in self._sources and self._sources[clean_id] not in resolved:
                resolved.append(self._sources[clean_id])
        return resolved


@dataclass
class AgentState:
    """Manages the full internal lifecycle and audit trail of an agent run."""

    repository_id: UUID
    question: str
    max_iterations: int
    max_tool_calls: int
    iteration: int = 0
    tool_call_count: int = 0
    status: AgentStatus = AgentStatus.RUNNING
    source_registry: SourceRegistry = field(default_factory=SourceRegistry)
    tool_activity: list[ToolActivitySummary] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str | None = None
    grounding_retries: int = 0

    def record_activity(
        self,
        tool: ToolName,
        parameters: dict[str, Any],
        success: bool,
        summary: str,
    ) -> None:
        """Record presentation-safe tool activity for UI inspection (no private reasoning)."""
        self.tool_activity.append(
            ToolActivitySummary(
                execution_order=len(self.tool_activity) + 1,
                tool=tool,
                parameters=parameters,
                success=success,
                summary=summary,
            )
        )

    def record_observation(
        self,
        tool: ToolName,
        arguments: dict[str, Any],
        success: bool,
        data: Any,
        error: str | None = None,
    ) -> None:
        """Record an observation for internal prompt history."""
        self.observations.append({
            "iteration": self.iteration,
            "tool": tool.value,
            "arguments": arguments,
            "success": success,
            "data": data,
            "error": error,
        })
