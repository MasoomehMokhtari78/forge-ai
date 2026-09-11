"""
ORM model registry.

Importing this package ensures all models are registered with Base.metadata.
This is required by Alembic (env.py) and by test fixtures that call
Base.metadata.create_all() / drop_all().
"""

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import IngestionStatus, Repository

__all__ = ["CodeChunk", "CodeFile", "IngestionStatus", "Repository"]

