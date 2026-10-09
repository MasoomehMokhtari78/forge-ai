"""
EngineeringKnowledge ORM model.

Represents a user-defined scope of engineering knowledge (e.g. Design Patterns,
SOLID principles, Clean Architecture guidelines) imported into ForgeAI.
"""

from datetime import datetime
import enum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.knowledge_chunk import KnowledgeChunk
    from app.models.knowledge_document import KnowledgeDocument


class KnowledgeStatus(str, enum.Enum):
    """Lifecycle states for knowledge scopes and documents."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class EngineeringKnowledge(Base):
    """A user-defined scope of engineering knowledge."""

    __tablename__ = "engineering_knowledge"

    __table_args__ = (
        Index("ix_engineering_knowledge_status", "status"),
        Index("ix_engineering_knowledge_created_at", "created_at"),
    )

    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
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
    documents: Mapped[list["KnowledgeDocument"]] = relationship(
        "KnowledgeDocument",
        back_populates="knowledge",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        "KnowledgeChunk",
        back_populates="knowledge",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<EngineeringKnowledge id={self.id} name={self.name!r} status={self.status}>"
