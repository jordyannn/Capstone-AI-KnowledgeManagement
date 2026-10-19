import json
from datetime import date

from sqlalchemy import func, select

from app.etl.load_corpus import load_corpus
from app.models import Document, DocumentPage
from app.models.document import STATUS_PENDING


def make_row(n: int = 1, **overrides) -> dict:
    row = {
        "id": f"id{n}",
        "judul": f"Judul {n}",
        "url_sumber": f"https://prodi.test/halaman-{n}/",
        "domain": "prodi.test",
        "sumber_dataset": "telkom_si_jakarta",
        "kategori": "akademik",
        "tier": "inti",
        "konten": f"Isi halaman nomor {n}. " * 20,
        "tanggal_publikasi": None,
        "bahasa": "id",
        "jumlah_karakter": 100,
        "terpotong_saat_scrape": False,
        "peran_akses_usulan": "publik",
        "hash_konten": f"hash{n:08d}",
    }
    row.update(overrides)
    return row


def write_jsonl(tmp_path, rows, raw_lines=()):
    path = tmp_path / "corpus.jsonl"
    lines = [json.dumps(r) for r in rows] + list(raw_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_loads_documents_and_pages_as_pending(db, tmp_path):
    path = write_jsonl(tmp_path, [make_row(1), make_row(2, tier="pendukung", kategori="berita")])
    report = load_corpus(db, path)

    assert (report.read, report.inserted, report.skipped_duplicate, report.invalid) == (2, 2, 0, [])
    docs = db.scalars(select(Document).order_by(Document.title)).all()
    assert [d.status for d in docs] == [STATUS_PENDING, STATUS_PENDING]
    assert docs[0].source_type == "seed"
    assert docs[0].allowed_roles == ["publik"]
    assert docs[0].category == "akademik" and docs[1].category == "berita"
    assert docs[0].tier == "inti" and docs[1].tier == "pendukung"
    assert docs[0].chunk_count == 0
    [page] = docs[0].pages
    assert page.page_number == 1 and page.text.startswith("Isi halaman nomor 1.")


def test_running_twice_does_not_duplicate_anything(db, tmp_path):
    path = write_jsonl(tmp_path, [make_row(1), make_row(2)])
    load_corpus(db, path)
    second = load_corpus(db, path)

    assert (second.read, second.inserted, second.skipped_duplicate) == (2, 0, 2)
    assert count(db, Document) == 2
    assert count(db, DocumentPage) == 2


def test_duplicate_hash_inside_one_file_is_skipped(db, tmp_path):
    path = write_jsonl(tmp_path, [make_row(1), make_row(2, hash_konten=make_row(1)["hash_konten"])])
    report = load_corpus(db, path)
    assert (report.inserted, report.skipped_duplicate) == (1, 1)


def test_published_date_and_truncated_flag_are_mapped(db, tmp_path):
    path = write_jsonl(tmp_path, [make_row(1, tanggal_publikasi="2025-03-04", terpotong_saat_scrape=True)])
    load_corpus(db, path)
    doc = db.scalar(select(Document))
    assert doc.published_at == date(2025, 3, 4)
    assert doc.is_truncated is True


def test_invalid_rows_are_reported_with_line_numbers_and_do_not_stop_the_load(db, tmp_path):
    bad_rows = [
        make_row(2, tier="vip"),
        make_row(3, konten=""),
        make_row(4, tanggal_publikasi="bukan-tanggal"),
        make_row(5, peran_akses_usulan="peran-ngawur"),
    ]
    missing_field = make_row(6)
    del missing_field["judul"]
    path = write_jsonl(tmp_path, [make_row(1), *bad_rows, missing_field], raw_lines=["{bukan json"])

    report = load_corpus(db, path)

    assert report.read == 7 and report.inserted == 1
    assert [n for n, _ in report.invalid] == [2, 3, 4, 5, 6, 7]
    reasons = dict(report.invalid)
    assert "tier" in reasons[2]
    assert "konten" in reasons[3]
    assert "tanggal_publikasi" in reasons[4]
    assert "peran-ngawur" in reasons[5]
    assert "judul" in reasons[6]
    assert "JSON" in reasons[7]
    assert count(db, Document) == 1


def test_known_role_codes_are_accepted(db, tmp_path):
    path = write_jsonl(tmp_path, [make_row(1, peran_akses_usulan="Dosen")])
    report = load_corpus(db, path)
    assert report.inserted == 1
    assert db.scalar(select(Document)).allowed_roles == ["dosen"]


def test_blank_lines_are_ignored(db, tmp_path):
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps(make_row(1)) + "\n\n   \n" + json.dumps(make_row(2)) + "\n", encoding="utf-8")
    report = load_corpus(db, path)
    assert (report.read, report.inserted) == (2, 2)


def test_report_text_lists_counts_and_failures(db, tmp_path):
    path = write_jsonl(tmp_path, [make_row(1), make_row(2, tier="vip")])
    text = load_corpus(db, path).render()
    assert "dibaca            : 2" in text
    assert "gagal validasi    : 1" in text
    assert "baris 2" in text
