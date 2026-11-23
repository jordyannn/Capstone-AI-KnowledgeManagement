"""ETL dokumen PDF resmi ke basis data terpusat, teks per halaman (untuk sitasi dokumen + halaman).

    python -m app.etl.load_pdfs /data/dokumen

Dijalankan di container worker (pypdf hanya ada di image worker). Idempoten: kunci duplikat adalah
SHA-256 isi file, jadi menjalankan ulang tidak menggandakan dokumen. Dokumen baru berstatus "pending"
dan di-index oleh ingest worker seperti dokumen lain.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Document, DocumentPage
from app.models.document import ROLE_PUBLIC, STATUS_PENDING

# Judul tampilan untuk sitasi. File yang tidak ada di sini memakai nama file.
KNOWN_TITLES = {
    "pedoman_akademik_2026.pdf": ("Pedoman Akademik Universitas Telkom 2026", "akademik"),
    "kalender_pendidikan_2026.pdf": ("Kalender Pendidikan Universitas Telkom 2026", "akademik"),
    "buku_kurikulum.pdf": ("Buku Kurikulum 2024 S1 Sistem Informasi Kampus Jakarta", "akademik"),
    "buku_panduan_ta_fri_2024.pdf": ("Buku Panduan Tugas Akhir FRI 2024", "tugas_akhir"),
    "buku_pedoman_kppm_fri_2025.pdf": ("Buku Pedoman KPPM FRI 2025", "kp_magang"),
    "buku_panduan_mbkm.pdf": ("Panduan Pembelajaran di Luar Program Studi (MBKM) 2024", "kp_magang"),
    "nde_pedoman_tak_2026.pdf": ("Nota Dinas Pembaruan Pedoman TAK 2026", "kemahasiswaan"),
    "sk_pedoman_tak.pdf": ("Pedoman Transkrip Aktivitas Kemahasiswaan (TAK) 2022", "kemahasiswaan"),
    "pedoman_penggunaan_ai_2025.pdf": ("Pedoman Penggunaan AI untuk Pembelajaran dan Pengajaran 2025", "akademik"),
}


def _clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def extract_pages(path: Path) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    return [_clean(page.extract_text() or "") for page in reader.pages]


def load_pdf(db: Session, path: Path, known_hashes: set[str]) -> str:
    content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    if content_hash in known_hashes:
        return "dilewati (duplikat)"
    pages = extract_pages(path)
    title, category = KNOWN_TITLES.get(path.name.lower(), (path.stem.replace("_", " "), "akademik"))
    document = Document(
        title=title,
        source_type="upload",
        source_url=None,
        domain=None,
        category=category,
        tier="inti",
        content_hash=content_hash,
        allowed_roles=[ROLE_PUBLIC],
        status=STATUS_PENDING,
    )
    kept = 0
    for number, text in enumerate(pages, start=1):
        if len(text) >= 40:  # halaman sampul/pemisah tanpa teks dilewati, nomor halaman tetap asli
            document.pages.append(DocumentPage(page_number=number, text=text))
            kept += 1
    if kept == 0:
        return "gagal: tidak ada teks (PDF hasil pindaian?)"
    db.add(document)
    db.commit()
    known_hashes.add(content_hash)
    return f"masuk ({kept}/{len(pages)} halaman berteks)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Muat semua PDF di sebuah folder ke documents + document_pages.")
    parser.add_argument("folder", type=Path)
    args = parser.parse_args(argv)
    files = sorted(args.folder.glob("*.pdf"))
    if not files:
        print(f"Tidak ada PDF di {args.folder}", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        known = set(db.scalars(select(Document.content_hash)))
        for path in files:
            try:
                print(f"{path.name}: {load_pdf(db, path, known)}")
            except Exception as exc:  # satu file rusak tidak menghentikan yang lain
                db.rollback()
                print(f"{path.name}: gagal: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
