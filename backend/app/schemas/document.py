import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source_type: str
    source_url: str | None
    domain: str | None
    category: str | None
    tier: str | None
    published_at: date | None
    allowed_roles: list[str]
    is_truncated: bool
    status: str
    error_message: str | None
    chunk_count: int
    created_at: datetime
    indexed_at: datetime | None


class ChunkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    page_number: int
    chunk_index: int
    text: str
    char_start: int
    char_end: int
    token_estimate: int


class CorpusRow(BaseModel):
    """Satu baris data/seed/corpus_clean.jsonl. Field tak dikenal diabaikan."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    id: str = Field(min_length=1)
    judul: str = Field(min_length=1, max_length=500)
    url_sumber: str = Field(min_length=1, max_length=2048)
    domain: str = Field(min_length=1, max_length=255)
    kategori: str = Field(min_length=1, max_length=64)
    tier: Literal["inti", "pendukung"]
    konten: str = Field(min_length=1)
    tanggal_publikasi: date | None = None
    terpotong_saat_scrape: bool
    peran_akses_usulan: str = Field(min_length=1)
    hash_konten: str = Field(min_length=8, max_length=64)

    @field_validator("tanggal_publikasi", mode="before")
    @classmethod
    def _blank_date_is_none(cls, value):
        return None if value in ("", None) else value
