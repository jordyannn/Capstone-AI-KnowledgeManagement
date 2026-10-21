import hashlib
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.ingest.indexer import MAX_CONSECUTIVE_FAILURES, count_pending, embedding_text, index_document, process_pending
from app.models import Chunk, Document, DocumentPage
from app.models.document import STATUS_FAILED, STATUS_INDEXED, STATUS_PENDING

LONG_TEXT = "\n\n".join(f"Paragraf {i}. " + " ".join(f"kalimat{j} berisi kata." for j in range(40)) for i in range(8))


class FakeEmbedder:
    """Vektor deterministik 8 dimensi dari hash teks."""

    def __init__(self, fail_on: str | None = None):
        self.fail_on = fail_on
        self.passage_calls = 0
        self.embedded_texts: list[str] = []

    def embed_passages(self, texts):
        self.passage_calls += 1
        self.embedded_texts.extend(texts)
        if self.fail_on and any(self.fail_on in t for t in texts):
            raise RuntimeError("model gagal")
        return [[b / 255 for b in hashlib.sha256(t.encode()).digest()[:8]] for t in texts]

    def embed_query(self, text):
        return self.embed_passages([text])[0]


class FakeCollection:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def upsert(self, ids, embeddings, documents, metadatas):
        for i, e, d, m in zip(ids, embeddings, documents, metadatas):
            self.items[i] = {"embedding": e, "document": d, "metadata": m}

    def delete(self, where):
        (key, value), = where.items()
        self.items = {i: v for i, v in self.items.items() if v["metadata"].get(key) != value}

    def count(self):
        return len(self.items)


def add_document(db, text=LONG_TEXT, title="Dokumen Uji", allowed_roles=None, published_at=None, status=STATUS_PENDING):
    doc = Document(
        title=title,
        source_type="seed",
        source_url="https://prodi.test/x",
        domain="prodi.test",
        category="akademik",
        tier="inti",
        published_at=published_at,
        content_hash=uuid.uuid4().hex,
        allowed_roles=allowed_roles or ["publik"],
        status=status,
    )
    doc.pages.append(DocumentPage(page_number=1, text=text))
    db.add(doc)
    db.commit()
    return doc


def test_index_document_writes_chunks_vectors_and_marks_indexed(db):
    doc = add_document(db, allowed_roles=["publik", "dosen"], published_at=date(2025, 1, 2))
    collection = FakeCollection()

    count = index_document(db, doc.id, FakeEmbedder(), collection)
    db.commit()

    db.refresh(doc)
    chunks = db.scalars(select(Chunk).where(Chunk.document_id == doc.id).order_by(Chunk.chunk_index)).all()
    assert count == len(chunks) > 1
    assert (doc.status, doc.chunk_count, doc.error_message) == (STATUS_INDEXED, count, None)
    assert doc.indexed_at is not None
    assert collection.count() == count
    assert {c.embedding_id for c in chunks} == set(collection.items)

    first = chunks[0]
    meta = collection.items[first.embedding_id]["metadata"]
    assert meta["document_id"] == str(doc.id) and meta["chunk_id"] == str(first.id)
    assert meta["title"] == "Dokumen Uji" and meta["source_url"] == "https://prodi.test/x"
    assert meta["category"] == "akademik" and meta["tier"] == "inti"
    assert meta["page_number"] == 1 and meta["chunk_index"] == 0
    assert meta["allowed_roles"] == "publik,dosen"
    assert meta["role_publik"] is True and meta["role_dosen"] is True
    assert meta["published_at"] == "2025-01-02"
    assert collection.items[first.embedding_id]["document"] == first.text


def test_vector_is_computed_from_title_plus_chunk_but_stored_text_stays_raw(db):
    doc = add_document(db, title="Kontak", text="WhatsApp +62 822-0000-0000 untuk respons cepat. " * 3)
    collection, embedder = FakeCollection(), FakeEmbedder()

    index_document(db, doc.id, embedder, collection)
    db.commit()

    chunks = db.scalars(select(Chunk).where(Chunk.document_id == doc.id)).all()
    assert embedder.embedded_texts == [f"Kontak. {c.text}" for c in chunks]
    for chunk in chunks:
        assert not chunk.text.startswith("Kontak")  # Postgres: teks asli
        assert collection.items[chunk.embedding_id]["document"] == chunk.text  # Chroma: teks asli
    assert embedding_text("Kontak", "isi") == "Kontak. isi"


def test_embedding_text_skips_blank_title():
    assert embedding_text("   ", "isi chunk") == "isi chunk"
    assert embedding_text("  Judul  ", "isi") == "Judul. isi"


def test_metadata_has_no_none_values_and_omits_missing_date(db):
    doc = add_document(db)
    collection = FakeCollection()
    index_document(db, doc.id, FakeEmbedder(), collection)
    for item in collection.items.values():
        assert None not in item["metadata"].values()
        assert "published_at" not in item["metadata"]


def test_chunk_offsets_point_into_the_page_text(db):
    doc = add_document(db)
    index_document(db, doc.id, FakeEmbedder(), FakeCollection())
    db.commit()
    for chunk in db.scalars(select(Chunk).where(Chunk.document_id == doc.id)):
        assert LONG_TEXT[chunk.char_start : chunk.char_end] == chunk.text
        assert chunk.token_estimate > 0


def test_reindex_replaces_old_chunks_in_postgres_and_chroma(db):
    doc = add_document(db)
    collection, embedder = FakeCollection(), FakeEmbedder()
    first = index_document(db, doc.id, embedder, collection)
    db.commit()
    old_ids = set(collection.items)

    second = index_document(db, doc.id, embedder, collection)
    db.commit()

    assert second == first
    assert collection.count() == first  # tidak menggandakan vektor
    assert set(collection.items).isdisjoint(old_ids)  # id baru, id lama sudah dihapus
    assert len(db.scalars(select(Chunk).where(Chunk.document_id == doc.id)).all()) == first


def test_reindex_of_one_document_leaves_other_documents_alone(db):
    a, b = add_document(db, title="A"), add_document(db, title="B")
    collection, embedder = FakeCollection(), FakeEmbedder()
    index_document(db, a.id, embedder, collection)
    index_document(db, b.id, embedder, collection)
    db.commit()
    before = {k for k, v in collection.items.items() if v["metadata"]["title"] == "B"}

    index_document(db, a.id, embedder, collection)
    db.commit()

    assert {k for k, v in collection.items.items() if v["metadata"]["title"] == "B"} == before


def test_document_without_text_fails_with_clear_error(db):
    doc = add_document(db, text="   \n  ")
    with pytest.raises(ValueError, match="tidak menghasilkan chunk"):
        index_document(db, doc.id, FakeEmbedder(), FakeCollection())


def test_process_pending_indexes_only_pending_documents(session_factory):
    with session_factory() as db:
        add_document(db, title="baru")
        add_document(db, title="sudah", status=STATUS_INDEXED)
        add_document(db, title="gagal", status=STATUS_FAILED)
    collection = FakeCollection()

    result = process_pending(session_factory, FakeEmbedder(), collection)

    assert (result.indexed, result.failed, result.aborted) == (1, 0, False)
    assert {v["metadata"]["title"] for v in collection.items.values()} == {"baru"}
    assert count_pending(session_factory) == 0


def test_failed_document_is_marked_and_does_not_stop_the_others(session_factory):
    with session_factory() as db:
        add_document(db, title="oke-1", text="Teks aman pertama. " * 30)
        add_document(db, title="rusak", text="MERACUN " * 30)
        add_document(db, title="oke-2", text="Teks aman kedua. " * 30)
    collection = FakeCollection()

    result = process_pending(session_factory, FakeEmbedder(fail_on="MERACUN"), collection)

    assert (result.indexed, result.failed) == (2, 1)
    with session_factory() as db:
        bad = db.scalar(select(Document).where(Document.title == "rusak"))
        assert bad.status == STATUS_FAILED
        assert "model gagal" in bad.error_message
        assert bad.chunk_count == 0
        assert db.scalars(select(Chunk).where(Chunk.document_id == bad.id)).all() == []
    assert "rusak" not in {v["metadata"]["title"] for v in collection.items.values()}


def test_failed_documents_are_not_retried_automatically(session_factory):
    with session_factory() as db:
        add_document(db, text="MERACUN " * 30)
    embedder = FakeEmbedder(fail_on="MERACUN")
    process_pending(session_factory, embedder, FakeCollection())
    calls = embedder.passage_calls

    process_pending(session_factory, embedder, FakeCollection())

    assert embedder.passage_calls == calls


def test_batch_aborts_after_consecutive_failures_and_leaves_rest_pending(session_factory):
    total = MAX_CONSECUTIVE_FAILURES + 2
    with session_factory() as db:
        for i in range(total):
            add_document(db, title=f"d{i}", text="MERACUN " * 30)

    result = process_pending(session_factory, FakeEmbedder(fail_on="MERACUN"), FakeCollection())

    assert result.aborted is True
    assert result.failed == MAX_CONSECUTIVE_FAILURES
    assert count_pending(session_factory) == total - MAX_CONSECUTIVE_FAILURES


def test_a_success_resets_the_consecutive_failure_counter(session_factory):
    with session_factory() as db:
        for i in range(MAX_CONSECUTIVE_FAILURES - 1):
            add_document(db, title=f"rusak{i}", text="MERACUN " * 30)
        add_document(db, title="oke", text="Teks aman. " * 30)
        for i in range(MAX_CONSECUTIVE_FAILURES - 1):
            add_document(db, title=f"rusak-lagi{i}", text="MERACUN " * 30)

    result = process_pending(session_factory, FakeEmbedder(fail_on="MERACUN"), FakeCollection())

    assert result.aborted is False
    assert (result.indexed, result.failed) == (1, 2 * (MAX_CONSECUTIVE_FAILURES - 1))
