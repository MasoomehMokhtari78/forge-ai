"""
Pydantic schemas for repository ingestion and retrieval.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.repository import IngestionStatus


class RepositoryCreate(BaseModel):
    """Request schema for repository ingestion."""

    url: str = Field(
        ...,
        description="Public GitHub repository URL (e.g. https://github.com/owner/repo)",
        examples=["https://github.com/fastapi/fastapi"],
    )


class RepositoryResponse(BaseModel):
    """Response schema for repository representation."""

    id: UUID
    url: str
    name: str
    status: IngestionStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
    ingested_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
