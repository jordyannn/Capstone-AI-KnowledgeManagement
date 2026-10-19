"""Memproses dokumen berstatus "pending": chunk -> embedding -> ChromaDB + tabel chunks.

Postgres dan ChromaDB tidak bisa di-commit atomik. Urutan di sini dipilih supaya kegagalan di
tengah jalan tidak meninggalkan data yatim yang bisa muncul di hasil pencarian:
  1. hapus chunk lama dokumen ini (Postgres + Chroma)  -> re-index selalu bersih
  2. tulis vektor ke Chroma
  3. tulis baris chunks + status "indexed" di Postgres dalam satu commit
Jika langkah 3 gagal, vektor di Chroma dihapus lagi (best effort); jika itu pun gagal, percobaan
berikutnya mulai dari langkah 1 sehingga tetap bersih.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.ingest.chunking import chunk_text
from app.ingest.embedding import Embedder
from app.ingest.vectorstore import chunk_metadata
from app.models import Chunk, Document
from app.models.document import STATUS_FAILED, STATUS_INDEXED, STATUS_PENDING

log = logging.getLogger("ingest")

UPSERT_BATCH = 256
MAX_CONSECUTIVE_FAILURES = 3


def embedding_text(title: str, body: str) -> str:
    """Teks yang dikirim ke model embedding: judul halaman di depan isi chunk.

    Banyak chunk tidak menyebut topik halamannya (mis. chunk di halaman "Kontak" yang isinya hanya
    nomor), sehingga vektornya tidak dekat dengan pertanyaan tentang topik itu. Pada 20 pertanyaan uji
    (Eksperimen Retrieval, 19 Okt 2026) top-1 naik 15 -> 16 dan MRR 0,793 -> 0,855.

    Hanya vektor yang memakai judul. Teks chunk yang disimpan (Postgres dan dokumen di ChromaDB)
    tetap asli agar sitasi dan cuplikan tidak tercampur judul. Mengubah fungsi ini berarti semua
    dokumen harus di-index ulang (`python -m app.ingest.requeue --all`).
    """
    title = title.strip()
    return f"{title}. {body}" if title else body


def _purge(db: Session, collection, document: Document) -> None:
    db.execute(delete(Chunk).where(Chunk.document_id == document.id))
    db.flush()
    db.expire(document, ["chunks"])
    collection.delete(where={"document_id": str(document.id)})


def index_document(db: Session, document_id: uuid.UUID, embedder: Embedder, collection) -> int:
    """Index satu dokumen. Mengembalikan jumlah chunk. Pemanggil yang melakukan commit."""
    document = db.get(Document, document_id)
    if document is None:
        raise LookupError(f"Dokumen {document_id} tidak ditemukan.")
    _purge(db, collection, document)

    chunks: list[Chunk] = []
    for page in document.pages:
        for piece in chunk_text(page.text):
            chunks.append(
                Chunk(
                    id=uuid.uuid4(),
                    document_id=document.id,
                    page_number=page.page_number,
                    chunk_index=piece.index,
                    text=piece.text,
                    char_start=piece.char_start,
                    char_end=piece.char_end,
                    token_estimate=piece.token_estimate,
                )
            )
    if not chunks:
        raise ValueError("Dokumen tidak menghasilkan chunk (teks kosong).")

    vectors = embedder.embed_passages([embedding_text(document.title, c.text) for c in chunks])
    if len(vectors) != len(chunks):
        raise RuntimeError(f"Jumlah vektor ({len(vectors)}) tidak sama dengan chunk ({len(chunks)}).")

    for i in range(0, len(chunks), UPSERT_BATCH):
        part = slice(i, i + UPSERT_BATCH)
        collection.upsert(
            ids=[str(c.id) for c in chunks[part]],
            embeddings=vectors[part],
            documents=[c.text for c in chunks[part]],
            metadatas=[chunk_metadata(document, c) for c in chunks[part]],
        )
    for chunk in chunks:
        chunk.embedding_id = str(chunk.id)

    db.add_all(chunks)
    document.chunk_count = len(chunks)
    document.status = STATUS_INDEXED
    document.error_message = None
    document.indexed_at = datetime.now(timezone.utc)
    return len(chunks)


@dataclass
class BatchResult:
    indexed: int = 0
    failed: int = 0
    aborted: bool = False  # berhenti dini karena kegagalan beruntun (kemungkinan masalah infrastruktur)


def _mark_failed(session_factory: sessionmaker, collection, document_id: uuid.UUID, error: Exception) -> None:
    try:
        collection.delete(where={"document_id": str(document_id)})
    except Exception:  # noqa: BLE001 - best effort; percobaan berikutnya membersihkan lagi
        log.warning("Gagal membersihkan vektor dokumen %s setelah error", document_id)
    with session_factory() as db:
        document = db.get(Document, document_id)
        if document is not None:
            db.execute(delete(Chunk).where(Chunk.document_id == document_id))
            document.status = STATUS_FAILED
            document.chunk_count = 0
            document.error_message = f"{type(error).__name__}: {error}"[:1000]
            db.commit()


def process_pending(session_factory: sessionmaker, embedder: Embedder, collection, limit: int = 20) -> BatchResult:
    with session_factory() as db:
        ids = list(
            db.scalars(
                select(Document.id)
                .where(Document.status == STATUS_PENDING)
                .order_by(Document.created_at, Document.id)
                .limit(limit)
            )
        )

    result = BatchResult()
    consecutive_failures = 0
    for document_id in ids:
        with session_factory() as db:
            try:
                count = index_document(db, document_id, embedder, collection)
                db.commit()
            except Exception as error:  # noqa: BLE001 - satu dokumen gagal tidak boleh menghentikan yang lain
                db.rollback()
                log.error("Gagal index dokumen %s: %s", document_id, error)
                _mark_failed(session_factory, collection, document_id, error)
                result.failed += 1
                consecutive_failures += 1
                if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                    result.aborted = True
                    log.error("%d kegagalan beruntun; batch dihentikan. Periksa model/ChromaDB.", consecutive_failures)
                    break
                continue
        consecutive_failures = 0
        result.indexed += 1
        log.info("Dokumen %s ter-index (%d chunk)", document_id, count)
    return result


def count_pending(session_factory: sessionmaker) -> int:
    with session_factory() as db:
        return db.scalar(select(func.count()).select_from(Document).where(Document.status == STATUS_PENDING)) or 0
