"""ETL korpus bersih (JSONL) ke basis data terpusat (SCRUM-36).

    python -m app.etl.load_corpus /data/seed/corpus_clean.jsonl

Idempoten: baris dengan content_hash yang sudah ada dilewati, jadi aman dijalankan berulang.
Dokumen baru berstatus "pending"; ingest worker yang akan meng-index-nya (SCRUM-38).
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Document, DocumentPage, Role
from app.models.document import ROLE_PUBLIC, STATUS_PENDING
from app.schemas.document import CorpusRow

BATCH_SIZE = 100


@dataclass
class LoadReport:
    read: int = 0
    inserted: int = 0
    skipped_duplicate: int = 0
    invalid: list[tuple[int, str]] = field(default_factory=list)  # (nomor baris, alasan)

    def render(self) -> str:
        lines = [
            f"dibaca            : {self.read}",
            f"baru dimasukkan   : {self.inserted}",
            f"dilewati (duplikat): {self.skipped_duplicate}",
            f"gagal validasi    : {len(self.invalid)}",
        ]
        lines += [f"  baris {n}: {reason}" for n, reason in self.invalid]
        return "\n".join(lines)


def _describe(err: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc'])) or '(baris)'}: {e['msg']}" for e in err.errors())


def _to_document(row: CorpusRow) -> Document:
    document = Document(
        title=row.judul,
        source_type="seed",
        source_url=row.url_sumber,
        domain=row.domain,
        category=row.kategori,
        tier=row.tier,
        published_at=row.tanggal_publikasi,
        content_hash=row.hash_konten,
        allowed_roles=[row.peran_akses_usulan.lower()],
        is_truncated=row.terpotong_saat_scrape,
        status=STATUS_PENDING,
    )
    # Halaman web = satu halaman. PDF nantinya punya banyak halaman (sitasi dokumen + halaman).
    document.pages.append(DocumentPage(page_number=1, text=row.konten))
    return document


def load_corpus(db: Session, path: Path) -> LoadReport:
    report = LoadReport()
    known_roles = {ROLE_PUBLIC, *db.scalars(select(Role.code))}
    seen_hashes = set(db.scalars(select(Document.content_hash)))
    batch: list[Document] = []

    def flush() -> None:
        if batch:
            db.add_all(batch)
            db.commit()
            report.inserted += len(batch)
            batch.clear()

    with path.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            if not raw.strip():
                continue
            report.read += 1
            try:
                row = CorpusRow.model_validate(json.loads(raw))
            except json.JSONDecodeError as err:
                report.invalid.append((line_no, f"JSON tidak valid: {err.msg}"))
                continue
            except ValidationError as err:
                report.invalid.append((line_no, _describe(err)))
                continue
            if row.peran_akses_usulan.lower() not in known_roles:
                report.invalid.append((line_no, f"peran_akses_usulan '{row.peran_akses_usulan}' tidak dikenal"))
                continue
            if row.hash_konten in seen_hashes:
                report.skipped_duplicate += 1
                continue
            seen_hashes.add(row.hash_konten)
            batch.append(_to_document(row))
            if len(batch) >= BATCH_SIZE:
                flush()
    flush()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Muat korpus JSONL ke tabel documents + document_pages.")
    parser.add_argument("path", type=Path, help="mis. /data/seed/corpus_clean.jsonl")
    args = parser.parse_args(argv)

    if not args.path.is_file():
        print(f"File tidak ditemukan: {args.path}", file=sys.stderr)
        return 2
    with SessionLocal() as db:
        report = load_corpus(db, args.path)
    print(report.render())
    return 1 if report.invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
