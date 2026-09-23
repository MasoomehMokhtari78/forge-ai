"""
Pydantic schemas for Phase 5 Agentic Software Engineering Assistant.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentStatus(str, Enum):
    """Execution status of an agent investigation run."""

    RUNNING = "running"
    COMPLETED = "completed"
    MAX_ITERATIONS = "max_iterations"
    MAX_TOOL_CALLS = "max_tool_calls"
    FAILED = "failed"


class ToolName(str, Enum):
    """Allowed read-only tool names."""

    SEARCH_CODE = "search_code"
    READ_FILE = "read_file"
    LIST_FILES = "list_files"


class SearchCodeArgs(BaseModel):
    """Arguments for search_code tool."""

    query: str = Field(..., min_length=1, max_length=1000, description="Semantic code query")
    top_k: int = Field(default=5, ge=1, le=50, description="Max chunks to retrieve")


class ReadFileArgs(BaseModel):
    """Arguments for read_file tool."""

    path: str = Field(..., min_length=1, description="Repository-relative file path")
    start_line: int | None = Field(default=None, ge=1, description="1-indexed starting line")
    end_line: int | None = Field(default=None, ge=1, description="1-indexed ending line")


class ListFilesArgs(BaseModel):
    """Arguments for list_files tool."""

    path: str | None = Field(default=None, description="Optional relative directory path")
    max_files: int = Field(default=100, ge=1, le=500, description="Max entries to return")


class ToolCall(BaseModel):
    """A validated structural tool call requested by the agent."""

    tool: ToolName
    arguments: dict[str, Any]


class ToolActivitySummary(BaseModel):
    """Presentation-safe summary of a tool execution for UI inspection.

    Explicitly excludes private reasoning, prompt dumps, or raw hidden tokens.
    """

    execution_order: int
    tool: ToolName
    parameters: dict[str, Any]
    success: bool
    summary: str


class SourceCitation(BaseModel):
    """Authoritative citation backed by a stable source ID in the agent's SourceRegistry."""

    source_id: str = Field(..., description="Stable source identifier (e.g. 'src_1')")
    path: str
    start_line: int
    end_line: int
    source_type: str = Field(..., description="'search' or 'read'")

    model_config = ConfigDict(frozen=True)


class AgentRequest(BaseModel):
    """Request payload to initiate an agent investigation."""

    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Software engineering question about the repository codebase.",
    )
    max_iterations: int | None = Field(
        default=None,
        ge=1,
        le=50,
        description="Optional override for maximum reasoning loop iterations.",
    )


class AgentResponse(BaseModel):
    """Response returned by the agent after investigation."""

    answer: str
    sources: list[SourceCitation]
    status: AgentStatus
    tool_calls_count: int
    iterations_count: int
    tool_activity: list[ToolActivitySummary]


class AgentMessageRole(str, Enum):
    """Roles in an agent conversation trajectory."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class AgentMessage(BaseModel):
    """Normalized message exchanged with an AgentLLMService."""

    role: AgentMessageRole
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_name: str | None = None  # Populated when role == TOOL


class AgentToolDefinition(BaseModel):
    """Normalized structural tool definition passed to an AgentLLMService."""

    name: ToolName
    description: str
    parameters: dict[str, Any]


class AgentLLMResponse(BaseModel):
    """Provider-independent response returned by an AgentLLMService."""

    final_text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)


def get_agent_tool_definitions() -> list[AgentToolDefinition]:
    """Return the normalized definitions of the three strictly read-only tools."""
    return [
        AgentToolDefinition(
            name=ToolName.SEARCH_CODE,
            description=(
                "Perform semantic code retrieval across indexed repository files. "
                "Returns matching code chunks with file paths, line numbers, and snippets."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Semantic search query describing code, functions, or concepts to find.",
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of top matching code chunks to return (1 to 20, default 5).",
                    },
                },
                "required": ["query"],
            },
        ),
        AgentToolDefinition(
            name=ToolName.READ_FILE,
            description=(
                "Read content from a specific repository file within an optional line range (up to 500 lines). "
                "Returns file path, actual line range read, total lines, and file content."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative POSIX file path to read.",
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "1-indexed starting line number (optional).",
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "1-indexed ending line number (optional).",
                    },
                },
                "required": ["path"],
            },
        ),
        AgentToolDefinition(
            name=ToolName.LIST_FILES,
            description=(
                "List directory entries (files and subdirectories) relative to the repository root. "
                "Useful for discovering repository structure and finding relevant files."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Repository-relative directory path to list (defaults to repository root).",
                    },
                    "max_files": {
                        "type": "integer",
                        "description": "Maximum entries to return (default 100, max 500).",
                    },
                },
                "required": [],
            },
        ),
    ]
