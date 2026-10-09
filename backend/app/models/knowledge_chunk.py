"""
KnowledgeChunk ORM model.

Represents a text chunk of a KnowledgeDocument with its vector embedding and page metadata.
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
    from app.models.engineering_knowledge import EngineeringKnowledge
    from app.models.knowledge_document import KnowledgeDocument


class KnowledgeChunk(Base):
    """Represents an indexed chunk of an engineering knowledge document with its vector embedding."""

    __tablename__ = "knowledge_chunks"

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_id_chunk_index"),
        Index("ix_knowledge_chunks_document_id_chunk_index", "document_id", "chunk_index"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    knowledge_id: Mapped[UUID] = mapped_column(
        ForeignKey("engineering_knowledge.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # 0-indexed position within the document
    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    # Raw text content of the chunk
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # 1-indexed page number in the original PDF if available
    page_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    # Fixed-dimension vector embedding matching settings.embedding_dimension
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
    document: Mapped["KnowledgeDocument"] = relationship("KnowledgeDocument", back_populates="chunks")
    knowledge: Mapped["EngineeringKnowledge"] = relationship("EngineeringKnowledge", back_populates="chunks")

    def __repr__(self) -> str:
        return (
            f"<KnowledgeChunk id={self.id} knowledge_id={self.knowledge_id} "
            f"document_id={self.document_id} index={self.chunk_index} page={self.page_number}>"
        )
