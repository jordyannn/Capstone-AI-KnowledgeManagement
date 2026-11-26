"""Riwayat percakapan mahasiswa dengan agen AI (F-11).

Fondasi untuk fitur berikutnya: eskalasi livechat/tiket melampirkan percakapan ini sebagai konteks,
umpan balik (F-12) disimpan per pesan, dan analitik (UC-07) menghitung dari tabel ini.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

SENDER_STUDENT = "mahasiswa"
SENDER_ASSISTANT = "asisten"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(200))  # pertanyaan pertama, dipotong
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )

    __table_args__ = (Index("ix_conversations_user_updated", "user_id", "updated_at"),)


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    sender: Mapped[str] = mapped_column(String(16))  # "mahasiswa" | "asisten"
    content: Mapped[str] = mapped_column(Text)
    # Sumber yang dikutip jawaban: [{number, title, page, url, score, snippet}]. Kosong untuk pesan mahasiswa.
    sources: Mapped[list] = mapped_column(JSON, default=list)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)  # alasan eskalasi
    feedback: Mapped[str | None] = mapped_column(String(16), nullable=True)  # F-12: "membantu" | "tidak"
    # Model yang menjawab (pesan asisten), mis. "Lokal (qwen2.5:7b)". Untuk pemantauan dan perbandingan.
    llm_used: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    __table_args__ = (Index("ix_messages_conversation_created", "conversation_id", "created_at"),)
