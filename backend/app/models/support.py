"""Eskalasi ke staf (F-10): livechat dan tiket dalam satu antrean.

Satu permintaan bantuan (SupportRequest) bisa berupa:
- "livechat": dibuat saat ada staf online; mahasiswa dan staf berbalas pesan langsung;
- "tiket": dibuat saat tidak ada staf online; pesan menunggu di antrean sampai staf membalas.
Keduanya memakai status yang sama (menunggu -> aktif -> selesai), sehingga antrean admin hanya satu
dan pesan yang dikirim saat staf offline otomatis menunggu di antrean.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

KIND_LIVECHAT = "livechat"
KIND_TICKET = "tiket"

STATUS_WAITING = "menunggu"
STATUS_ACTIVE = "aktif"
STATUS_CLOSED = "selesai"
STATUSES = (STATUS_WAITING, STATUS_ACTIVE, STATUS_CLOSED)

SENDER_STUDENT = "mahasiswa"
SENDER_STAFF = "staf"

# Kategori tiket. Disimpan sebagai kode; label tampilan ada di frontend.
CATEGORIES = ("akademik", "tugas_akhir_kppm", "administrasi", "keuangan", "lainnya")

# Peran yang boleh melayani antrean. Peran lain (mahasiswa, dosen, kaprodi) diperlakukan sebagai peminta.
STAFF_ROLES = ("admin", "staf")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # Percakapan AI yang dilampirkan sebagai konteks. Tetap ada walau percakapan dihapus mahasiswa.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16))  # "livechat" | "tiket"
    category: Mapped[str] = mapped_column(String(32))
    subject: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default=STATUS_WAITING)
    assigned_staff_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list["SupportMessage"]] = relationship(
        back_populates="request", cascade="all, delete-orphan", order_by="SupportMessage.created_at"
    )

    __table_args__ = (
        Index("ix_support_requests_student_updated", "student_id", "updated_at"),
        Index("ix_support_requests_status_updated", "status", "updated_at"),
    )


class SupportMessage(Base):
    __tablename__ = "support_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("support_requests.id", ondelete="CASCADE"))
    sender_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    sender_role: Mapped[str] = mapped_column(String(16))  # "mahasiswa" | "staf"
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    request: Mapped[SupportRequest] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_support_messages_request_created", "request_id", "created_at"),)


class StaffPresence(Base):
    """Status online staf. Online = toggle aktif DAN halaman admin masih mengirim heartbeat."""

    __tablename__ = "staff_presence"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
