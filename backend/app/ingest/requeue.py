"""Kembalikan dokumen ke "pending" agar di-index ulang oleh worker.

    python -m app.ingest.requeue --failed     # hanya yang gagal (bawaan)
    python -m app.ingest.requeue --all        # semua; wajib setelah mengganti EMBEDDING_MODEL
"""

import argparse

from sqlalchemy import update

from app.core.db import SessionLocal
from app.models import Document
from app.models.document import STATUS_FAILED, STATUS_PENDING


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--failed", action="store_true", help="hanya dokumen berstatus failed (bawaan)")
    group.add_argument("--all", action="store_true", help="semua dokumen")
    args = parser.parse_args(argv)

    stmt = update(Document).values(status=STATUS_PENDING, error_message=None)
    if not args.all:
        stmt = stmt.where(Document.status == STATUS_FAILED)
    with SessionLocal() as db:
        count = db.execute(stmt).rowcount
        db.commit()
    print(f"{count} dokumen dikembalikan ke pending.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
