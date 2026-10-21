"""kolom SSO pada users: auth_provider, external_id, password_hash nullable

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-21
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table: mengubah nullable butuh menulis ulang tabel di SQLite; di PostgreSQL
    # tetap menjadi ALTER biasa.
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("auth_provider", sa.String(16), nullable=False, server_default="local"))
        batch.add_column(sa.Column("external_id", sa.String(64), nullable=True))
        batch.alter_column("password_hash", existing_type=sa.String(255), nullable=True)
    op.create_index("ix_users_external_id", "users", ["external_id"], unique=True)


def downgrade() -> None:
    orphans = op.get_bind().execute(sa.text("SELECT count(*) FROM users WHERE password_hash IS NULL")).scalar()
    if orphans:
        # Menghapus kolom ini diam-diam akan membuat user SSO tidak bisa login sama sekali.
        raise RuntimeError(
            f"{orphans} user SSO tidak punya password_hash. Hapus atau beri mereka sandi sebelum downgrade."
        )
    op.drop_index("ix_users_external_id", table_name="users")
    with op.batch_alter_table("users") as batch:
        batch.alter_column("password_hash", existing_type=sa.String(255), nullable=False)
        batch.drop_column("external_id")
        batch.drop_column("auth_provider")
