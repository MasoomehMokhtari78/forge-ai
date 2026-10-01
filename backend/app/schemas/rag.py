"""
Pydantic schemas for code retrieval and RAG operations.
"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.core.config import settings


class ChunkRetrievalResult(BaseModel):
    """Represents a single retrieved code chunk with its similarity score."""

    chunk_id: UUID
    file_id: UUID
    path: str
    content: str
    start_line: int
    end_line: int
    similarity: float = Field(
        ...,
        description="Cosine similarity score in the range [0.0, 1.0] for normalized embeddings.",
    )

    model_config = ConfigDict(from_attributes=True)


class SearchRequest(BaseModel):
    """Request payload for semantic code search."""

    query: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Natural language or code query to search for.",
    )
    top_k: int = Field(
        default=settings.rag_top_k,
        ge=1,
        le=50,
        description="Maximum number of relevant chunks to retrieve.",
    )
    similarity_threshold: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional minimum cosine similarity threshold in [0.0, 1.0].",
    )


class SearchResponse(BaseModel):
    """Response payload for semantic code search."""

    repository_id: UUID
    query: str
    results: list[ChunkRetrievalResult]


class Citation(BaseModel):
    """Authoritative source citation derived directly from retrieved chunk metadata."""

    path: str
    start_line: int
    end_line: int

    @computed_field
    @property
    def file_path(self) -> str:
        return self.path

    model_config = ConfigDict(frozen=True)


class ChatRequest(BaseModel):
    """Request payload for repository code question-answering."""

    question: str | None = Field(
        default=None,
        description="User question regarding the repository codebase.",
    )
    message: str | None = Field(
        default=None,
        description="Alternative alias for question.",
    )

    @model_validator(mode="before")
    @classmethod
    def validate_question_or_message(cls, data: Any) -> Any:
        if isinstance(data, dict):
            q = data.get("question") or data.get("message")
            if not q or not isinstance(q, str) or not q.strip():
                raise ValueError("Question or message cannot be empty.")
            data["question"] = q.strip()
            data["message"] = q.strip()
        elif isinstance(data, str) and data.strip():
            return {"question": data.strip(), "message": data.strip()}
        return data


class ChatResponse(BaseModel):
    """Response payload for repository code question-answering."""

    answer: str
    sources: list[Citation]
