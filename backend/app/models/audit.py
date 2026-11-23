"""Log audit (F-15): catatan aktivitas penting admin/staf dan upaya login yang gagal.

Hanya ditambah, tidak pernah diubah atau dihapus lewat aplikasi. Email pelaku disimpan sebagai salinan
(actor_email) supaya catatan tetap terbaca walaupun akunnya kelak dihapus.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Kode aksi. Label tampilan ada di frontend.
LOGIN = "login"
LOGIN_FAILED = "login_gagal"
SUPPORT_REPLY = "bantuan_balas"
SUPPORT_CLOSE = "bantuan_tutup"
PRESENCE_ONLINE = "status_online"
PRESENCE_OFFLINE = "status_offline"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    action: Mapped[str] = mapped_column(String(32))
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)  # mis. "support_request"
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_audit_logs_created", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )
