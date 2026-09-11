"""
Shared SQLAlchemy declarative base.

All ORM models must inherit from this Base so that:
  - SQLAlchemy can track them as part of the same metadata graph.
  - Alembic can discover them for autogenerate migrations.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared base class for all SQLAlchemy ORM models."""
    pass
