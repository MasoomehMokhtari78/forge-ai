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
    auto_index: bool = Field(
        default=True,
        description="Automatically index source code chunks and generate vector embeddings after ingestion.",
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


class FileMetadata(BaseModel):
    """Metadata for a source code file within a repository."""

    path: str = Field(description="Normalized POSIX relative path from repository root")
    size_bytes: int = Field(description="File size in bytes")
    extension: str = Field(description="File extension with leading dot")


class RepositoryFilesResponse(BaseModel):
    """Response containing the list of files in a repository."""

    repository_id: UUID
    total_files: int
    files: list[FileMetadata]


class FileContentResponse(BaseModel):
    """Response containing the complete text content of a file."""

    repository_id: UUID
    path: str
    total_lines: int
    size_bytes: int
    content: str
