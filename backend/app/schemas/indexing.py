"""
Pydantic schemas for code indexing operations.
"""

from uuid import UUID

from pydantic import BaseModel, ConfigDict


class IndexingResponse(BaseModel):
    """Response schema returned after triggering repository indexing."""

    repository_id: UUID
    status: str
    files_indexed: int
    chunks_created: int

    model_config = ConfigDict(from_attributes=True)


class IndexSummaryResponse(BaseModel):
    """Summary schema showing the current index metrics of a repository."""

    repository_id: UUID
    files_indexed: int
    chunks_created: int

    model_config = ConfigDict(from_attributes=True)
