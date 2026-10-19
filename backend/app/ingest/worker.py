"""Ingest worker: polling dokumen "pending" di Postgres lalu meng-index-nya.

    python -m app.ingest.worker

Polling sederhana sudah cukup untuk skala ini; belum perlu message queue.
"""

import logging
import signal
import threading

from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.ingest.embedding import SentenceTransformerEmbedder
from app.ingest.indexer import count_pending, process_pending
from app.ingest.vectorstore import get_collection

log = logging.getLogger("ingest")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # satu baris INFO per request ke Chroma menutupi log penting
    settings = get_settings()
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    embedder = SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_batch_size)
    collection = None
    log.info("worker ready (model=%s, chroma=%s:%s)", settings.embedding_model, settings.chroma_host, settings.chroma_port)

    while not stop.is_set():
        try:
            if count_pending(SessionLocal) == 0:
                stop.wait(settings.worker_poll_seconds)
                continue
            # Muat model dan sambung Chroma sebelum menyentuh dokumen: kegagalan infrastruktur
            # di sini membuat dokumen tetap "pending", bukan ditandai "failed".
            if collection is None:
                collection = get_collection(settings)
            log.info("Memuat model embedding %s (unduhan pertama bisa beberapa menit)", settings.embedding_model)
            embedder.load()
            result = process_pending(SessionLocal, embedder, collection)
            log.info("Batch selesai: %d ter-index, %d gagal", result.indexed, result.failed)
            if result.aborted:
                stop.wait(settings.worker_poll_seconds * 6)
        except (SQLAlchemyError, OSError, RuntimeError) as error:
            # Termasuk: tabel belum dimigrasi, Postgres/Chroma belum siap, model gagal diunduh.
            log.error("Siklus gagal, dicoba lagi nanti: %s", error)
            collection = None
            stop.wait(settings.worker_poll_seconds * 2)
    log.info("worker berhenti")


if __name__ == "__main__":
    main()
