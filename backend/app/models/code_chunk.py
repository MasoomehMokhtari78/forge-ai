"""
CodeChunk ORM model.

Represents a text chunk of a CodeFile with its vector embedding.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.models.base import Base

if TYPE_CHECKING:
    from app.models.code_file import CodeFile


class CodeChunk(Base):
    """Represents an indexed chunk of code with its vector embedding."""

    __tablename__ = "code_chunks"

    __table_args__ = (
        # A file must not contain duplicate chunk indexes
        UniqueConstraint("file_id", "chunk_index", name="uq_code_chunks_file_id_chunk_index"),
        Index("ix_code_chunks_file_id_chunk_index", "file_id", "chunk_index"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    file_id: Mapped[UUID] = mapped_column(
        ForeignKey("code_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 0-indexed position within the file
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Raw code content of the chunk
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # 1-indexed starting line number in original file
    start_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # 1-indexed ending line number in original file (inclusive)
    end_line: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Fixed-dimension vector embedding (e.g. 384 for BAAI/bge-small-en-v1.5)
    embedding: Mapped[list[float]] = mapped_column(
        Vector(settings.embedding_dimension),
        nullable=False,
    )


    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Relationships
    file: Mapped["CodeFile"] = relationship("CodeFile", back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<CodeChunk id={self.id} file_id={self.file_id} "
            f"index={self.chunk_index} lines={self.start_line}-{self.end_line}>"
        )
