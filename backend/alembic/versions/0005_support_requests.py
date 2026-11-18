"""support_requests, support_messages, staff_presence (eskalasi livechat/tiket, F-10)

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("subject", sa.String(200), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="menunggu"),
        sa.Column("assigned_staff_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_support_requests_student_updated", "support_requests", ["student_id", "updated_at"])
    op.create_index("ix_support_requests_status_updated", "support_requests", ["status", "updated_at"])

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "request_id", sa.Uuid(), sa.ForeignKey("support_requests.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sender_role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_support_messages_request_created", "support_messages", ["request_id", "created_at"])

    op.create_table(
        "staff_presence",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("online", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("staff_presence")
    op.drop_index("ix_support_messages_request_created", table_name="support_messages")
    op.drop_table("support_messages")
    op.drop_index("ix_support_requests_status_updated", table_name="support_requests")
    op.drop_index("ix_support_requests_student_updated", table_name="support_requests")
    op.drop_table("support_requests")
