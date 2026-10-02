"""
Pydantic schemas for Knowledge-Guided Analysis.
"""

from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CodeScopeType(str, Enum):
    """Scope of code selection for repository analysis."""

    REPOSITORY = "repository"
    FILE = "file"


class CodeScope(BaseModel):
    """Defines the code boundary within a repository."""

    type: CodeScopeType = Field(
        default=CodeScopeType.REPOSITORY,
        description="Target code scope: 'repository' for whole-repo search, or 'file' for single-file analysis.",
    )
    path: str | None = Field(
        default=None,
        description="Repository-relative file path (required if type == 'file').",
        examples=["src/services/PaymentService.ts"],
    )


class KnowledgeAnalysisRequest(BaseModel):
    """Request payload for knowledge-guided code analysis."""

    repository_id: UUID = Field(
        ...,
        description="Authoritative UUID of the target repository.",
    )
    knowledge_id: UUID = Field(
        ...,
        description="Authoritative UUID of the engineering knowledge scope to apply.",
    )
    code_scope: CodeScope = Field(
        default_factory=lambda: CodeScope(type=CodeScopeType.REPOSITORY),
        description="Code scope boundary within the repository.",
    )
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Software engineering or architectural question to analyze.",
        examples=["What design pattern would you recommend for refactoring this file?"],
    )


class AnalysisSource(BaseModel):
    """Authoritative citation for an evidence block included in the analysis."""

    source_id: str = Field(..., description="Stable source identifier (e.g. 'src_1')")
    type: str = Field(..., description="'repository' or 'knowledge'")
    label: str = Field(..., description="Human-readable citation label (e.g. 'PaymentService.ts:42-91' or 'Design Patterns Reference.pdf, page 87')")
    path: str = Field(..., description="File path or document filename")
    start_line: int | None = Field(default=None, description="Starting line number for code files")
    end_line: int | None = Field(default=None, description="Ending line number for code files")
    page_number: int | None = Field(default=None, description="Page number for knowledge documents")

    model_config = ConfigDict(frozen=True)


class AnalysisResponse(BaseModel):
    """Response payload containing grounded answer and verified sources."""

    answer: str = Field(..., description="LLM-generated answer grounded in retrieved repository and knowledge evidence.")
    sources: list[AnalysisSource] = Field(
        default_factory=list,
        description="Verified citations corresponding strictly to retrieved chunks included in the LLM context.",
    )
