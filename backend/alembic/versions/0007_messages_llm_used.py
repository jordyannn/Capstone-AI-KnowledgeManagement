"""messages.llm_used (model yang menjawab, untuk pilihan model lokal/komersial)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-26
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("llm_used", sa.String(80), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "llm_used")
