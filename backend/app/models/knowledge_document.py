"""
KnowledgeDocument ORM model.

Represents an individual document (e.g. uploaded PDF) belonging to an EngineeringKnowledge scope.
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.engineering_knowledge import KnowledgeStatus

if TYPE_CHECKING:
    from app.models.engineering_knowledge import EngineeringKnowledge
    from app.models.knowledge_chunk import KnowledgeChunk


class KnowledgeDocument(Base):
    """Represents a document within a knowledge scope."""

    __tablename__ = "knowledge_documents"

    __table_args__ = (
        UniqueConstraint("knowledge_id", "filename", name="uq_knowledge_documents_knowledge_id_filename"),
        Index("ix_knowledge_documents_knowledge_id_filename", "knowledge_id", "filename"),
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

    filename: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    source_type: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="pdf",
    )

    file_size_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )

    status: Mapped[KnowledgeStatus] = mapped_column(
        Enum(
            KnowledgeStatus,
            name="knowledgestatus",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=KnowledgeStatus.PENDING,
        server_default=KnowledgeStatus.PENDING.value,
    )

    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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
    knowledge: Mapped["EngineeringKnowledge"] = relationship(
        "EngineeringKnowledge",
        back_populates="documents",
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk",
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<KnowledgeDocument id={self.id} filename={self.filename!r} knowledge_id={self.knowledge_id}>"
