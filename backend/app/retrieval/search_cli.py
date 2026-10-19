"""Uji retrieval dari terminal (belum ada endpoint publik).

    python -m app.retrieval.search_cli "bagaimana alur penundaan pembayaran BPP?" --k 5
    python -m app.retrieval.search_cli "..." --role mahasiswa

Tanpa --role hanya dokumen "publik" yang dicari. Harus dijalankan di container worker
(butuh model embedding): docker compose exec worker python -m app.retrieval.search_cli ...
"""

import argparse
import textwrap

from app.core.config import get_settings
from app.ingest.embedding import SentenceTransformerEmbedder
from app.ingest.vectorstore import get_collection
from app.retrieval.search import search


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Cari chunk dokumen paling relevan.")
    parser.add_argument("query")
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--role", default=None, help="kode peran, mis. mahasiswa, dosen (bawaan: hanya publik)")
    parser.add_argument("--chars", type=int, default=240, help="panjang cuplikan teks")
    args = parser.parse_args(argv)

    settings = get_settings()
    embedder = SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_batch_size)
    hits = search(args.query, embedder, get_collection(settings), k=args.k, role=args.role)

    print(f'Pertanyaan: "{args.query}"  (k={args.k}, peran={args.role or "-"})')
    if not hits:
        print("  (tidak ada hasil)")
    for rank, hit in enumerate(hits, start=1):
        snippet = textwrap.shorten(hit.text, width=args.chars, placeholder="...")
        print(f"{rank}. skor={hit.score:.3f}  {hit.title}  [hal. {hit.page_number}]")
        print(f"   {hit.source_url}")
        print(f"   {snippet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
