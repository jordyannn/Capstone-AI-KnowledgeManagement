import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base

# Nilai khusus di allowed_roles: dokumen boleh dibaca siapa saja, termasuk yang belum login.
ROLE_PUBLIC = "publik"

STATUS_PENDING = "pending"
STATUS_INDEXED = "indexed"
STATUS_FAILED = "failed"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(String(16))  # "web" | "upload" | "seed"
    source_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tier: Mapped[str | None] = mapped_column(String(16), nullable=True)  # "inti" | "pendukung"
    published_at: Mapped[date | None] = mapped_column(Date, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Kode peran dari tabel roles, atau "publik". Dipakai filter akses saat retrieval (SCRUM-44).
    allowed_roles: Mapped[list[str]] = mapped_column(JSON, default=lambda: [ROLE_PUBLIC])
    is_truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_PENDING)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    pages: Mapped[list["DocumentPage"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="DocumentPage.page_number"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan", order_by="Chunk.page_number, Chunk.chunk_index"
    )

    __table_args__ = (Index("ix_documents_status", "status"),)


class DocumentPage(Base):
    """Teks per halaman, agar sitasi "dokumen + halaman" (SCRUM-47) bisa langsung dipakai.
    Halaman web selalu page_number = 1."""

    __tablename__ = "document_pages"

    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text)

    document: Mapped[Document] = relationship(back_populates="pages")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer)  # urutan di dalam halaman
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)  # offset di DocumentPage.text
    char_end: Mapped[int] = mapped_column(Integer)
    token_estimate: Mapped[int] = mapped_column(Integer)
    embedding_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # id di ChromaDB

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", "chunk_index", name="uq_chunks_position"),
        Index("ix_chunks_document_id", "document_id"),
    )
