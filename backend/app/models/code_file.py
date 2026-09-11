"""
CodeFile ORM model.

Represents an individual source code file belonging to an ingested Repository.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.code_chunk import CodeChunk
    from app.models.repository import Repository


class CodeFile(Base):
    """Represents a source file within an ingested repository."""

    __tablename__ = "code_files"

    __table_args__ = (
        # A repository must not contain duplicate file paths
        UniqueConstraint("repository_id", "path", name="uq_code_files_repository_id_path"),
        Index("ix_code_files_repository_id_path", "repository_id", "path"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    repository_id: Mapped[UUID] = mapped_column(
        ForeignKey("repositories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relative POSIX path from repository root (e.g. "src/main.py")
    path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # File extension including leading dot (e.g. ".py", ".ts"), or empty string
    extension: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Size in bytes
    size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Relationships
    repository: Mapped["Repository"] = relationship("Repository", back_populates="files")
    chunks: Mapped[list["CodeChunk"]] = relationship(
        "CodeChunk",
        back_populates="file",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<CodeFile id={self.id} path={self.path!r} repository_id={self.repository_id}>"
