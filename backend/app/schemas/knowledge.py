"""
Pydantic schemas for engineering knowledge scopes and documents.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.engineering_knowledge import KnowledgeStatus


class KnowledgeCreate(BaseModel):
    """Request schema for creating a new engineering knowledge scope."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Name of the engineering knowledge scope (e.g. 'Design Pattern Guidance', 'SOLID Principles')",
        examples=["Design Pattern Guidance"],
    )
    description: str | None = Field(
        default=None,
        max_length=2000,
        description="Optional description of the engineering knowledge scope",
        examples=["Guidelines and architectural pattern definitions for codebase evaluation."],
    )


class KnowledgeDocumentResponse(BaseModel):
    """Response schema for a document within an engineering knowledge scope."""

    id: UUID
    knowledge_id: UUID
    filename: str
    source_type: str
    file_size_bytes: int
    status: KnowledgeStatus
    error_message: str | None = None
    chunks_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeResponse(BaseModel):
    """Response schema for an engineering knowledge scope."""

    id: UUID
    name: str
    description: str | None = None
    status: KnowledgeStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    documents: list[KnowledgeDocumentResponse] = []

    model_config = ConfigDict(from_attributes=True)
