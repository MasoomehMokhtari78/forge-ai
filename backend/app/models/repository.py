"""
Repository ORM model.

Represents a GitHub (or other public) repository that has been imported
into ForgeAI for indexing and querying.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Enum, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.code_file import CodeFile



class IngestionStatus(str, enum.Enum):
    """Lifecycle states for repository ingestion.

    Inherits from `str` so values serialise as plain strings in JSON
    responses and are stored as the string value in the database —
    no custom serialisation logic is required.

    State transitions:
        PENDING -> PROCESSING -> COMPLETED
                             -> FAILED
    """

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class Repository(Base):
    """A source code repository imported into ForgeAI.

    Fields deliberately excluded from the initial model:
      - owner / branch / language / stars: GitHub API metadata not needed until
        GitHub integration is introduced in a later phase.
      - local_path: Where the repo is cloned on disk. Added in Phase 2 (file
        discovery) when it is actually used.
    """

    __tablename__ = "repositories"

    __table_args__ = (
        # Filtered queries by status are common (e.g. "show all pending").
        Index("ix_repositories_status", "status"),
        # Listing repositories in creation order is the natural default sort.
        Index("ix_repositories_created_at", "created_at"),
    )

    # UUID generated in Python so the ID is available before the DB round-trip.
    id: Mapped[UUID] = mapped_column(
        primary_key=True,
        default=uuid4,
    )

    # The canonical identifier for a repository. Unique to prevent duplicate
    # import jobs for the same repository.
    url: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        unique=True,
    )

    # Human-readable label derived from the URL (e.g. "torvalds/linux").
    # Always required; never null.
    name: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    # Ingestion lifecycle state. Native PostgreSQL ENUM enforces validity at the
    # database level; the Python enum enforces it at the application level.
    status: Mapped[IngestionStatus] = mapped_column(
        Enum(
            IngestionStatus,
            name="ingestionstatus",
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=IngestionStatus.PENDING,
        server_default=IngestionStatus.PENDING.value,
    )

    # Populated only when status == FAILED. Null in all other states.
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Set by the database at INSERT time; never written by application code.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # Updated by SQLAlchemy at the ORM level on every UPDATE statement.
    # This keeps the logic visible in Python rather than hidden in a DB trigger.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # Set once when ingestion completes successfully. Null until then.
    ingested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    files: Mapped[list["CodeFile"]] = relationship(
        "CodeFile",
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Repository id={self.id} name={self.name!r} status={self.status}>"

