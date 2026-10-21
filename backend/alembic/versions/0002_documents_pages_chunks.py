"""documents, document_pages, chunks

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_url", sa.String(2048), nullable=True),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("tier", sa.String(16), nullable=True),
        sa.Column("published_at", sa.Date(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("allowed_roles", sa.JSON(), nullable=False),
        sa.Column("is_truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_status", "documents", ["status"])

    op.create_table(
        "document_pages",
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("page_number", sa.Integer(), primary_key=True),
        sa.Column("text", sa.Text(), nullable=False),
    )

    op.create_table(
        "chunks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("document_id", sa.Uuid(), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_estimate", sa.Integer(), nullable=False),
        sa.Column("embedding_id", sa.String(64), nullable=True),
        sa.UniqueConstraint("document_id", "page_number", "chunk_index", name="uq_chunks_position"),
    )
    op.create_index("ix_chunks_document_id", "chunks", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_chunks_document_id", table_name="chunks")
    op.drop_table("chunks")
    op.drop_table("document_pages")
    op.drop_index("ix_documents_status", table_name="documents")
    op.drop_table("documents")
