"""update_embedding_dimension_to_384

Revision ID: a4b9d1a681ab
Revises: 6e00d430985d
Create Date: 2026-09-11 12:34:07.124482

"""
from typing import Sequence, Union

from alembic import op
import pgvector
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4b9d1a681ab'
down_revision: Union[str, None] = '6e00d430985d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Clear previous indexing data which used the 1536-dimensional space
    op.execute("TRUNCATE TABLE code_files CASCADE;")

    # Alter the embedding vector dimension to 384
    op.alter_column(
        'code_chunks',
        'embedding',
        existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=1536),
        type_=pgvector.sqlalchemy.vector.VECTOR(dim=384),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute("TRUNCATE TABLE code_files CASCADE;")
    op.alter_column(
        'code_chunks',
        'embedding',
        existing_type=pgvector.sqlalchemy.vector.VECTOR(dim=384),
        type_=pgvector.sqlalchemy.vector.VECTOR(dim=1536),
        existing_nullable=False,
    )

