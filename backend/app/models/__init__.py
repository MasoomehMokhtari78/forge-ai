"""
ORM model registry.

Importing this package ensures all models are registered with Base.metadata.
This is required by Alembic (env.py) and by test fixtures that call
Base.metadata.create_all() / drop_all().
"""

from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.engineering_knowledge import EngineeringKnowledge, KnowledgeStatus
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.repository import IngestionStatus, Repository

__all__ = [
    "CodeChunk",
    "CodeFile",
    "EngineeringKnowledge",
    "IngestionStatus",
    "KnowledgeChunk",
    "KnowledgeDocument",
    "KnowledgeStatus",
    "Repository",
]

