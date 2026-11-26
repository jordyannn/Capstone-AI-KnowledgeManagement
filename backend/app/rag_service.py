"""Layanan retrieval internal (dijalankan dari image worker, karena butuh model embedding).

Backend memanggil POST /search; layanan ini tidak dibuka ke host maupun ke Nginx.
    uvicorn app.rag_service:app --host 0.0.0.0 --port 8001
"""

import re
from dataclasses import asdict

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.ingest.embedding import SentenceTransformerEmbedder
from app.ingest.vectorstore import get_collection
from app.retrieval.hybrid import BM25Index, fuse, is_toc
from app.retrieval.search import search

app = FastAPI(title="KMS retrieval service")
_state: dict = {}


def _ready():
    if "embedder" not in _state:
        settings = get_settings()
        embedder = SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_batch_size)
        embedder.load()
        _state["embedder"] = embedder
        _state["collection"] = get_collection(settings)
    return _state["embedder"], _state["collection"]


def _bm25(refresh: bool = False) -> BM25Index:
    # Dibangun dari isi ChromaDB. Dokumen baru masuk setelah /reload dipanggil atau service restart.
    if refresh or "bm25" not in _state:
        _state["bm25"] = BM25Index.from_collection(_ready()[1])
    return _state["bm25"]


@app.on_event("startup")
def _warm_up() -> None:
    _ready()


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=5, ge=1, le=20)
    role: str | None = None


@app.get("/health")
def health() -> dict:
    _ready()
    return {"status": "ok"}


@app.post("/reload")
def reload_index() -> dict:
    return {"chunks": len(_bm25(refresh=True).docs)}


# Istilah sehari-hari mahasiswa yang berbeda dengan istilah resmi di dokumen. Contoh (23 Nov):
# "Kapan batas KRS?" dieskalasi karena dokumen Tel-U memakai "PRS"/"rencana studi" (18 potongan),
# sedangkan "KRS" hanya muncul di 3 potongan.
SYNONYMS = {
    "krs": "rencana studi PRS registrasi mata kuliah",
    "khs": "kartu hasil studi nilai",
    "her registrasi": "registrasi ulang pembayaran BPP",
    "ukt": "BPP biaya penyelenggaraan pendidikan",
    "sidang ta": "sidang tugas akhir",
}


def expand_query(query: str) -> str:
    low = query.lower()
    extra = [v for k, v in SYNONYMS.items() if re.search(rf"\b{re.escape(k)}\b", low)]
    return f"{query} ({' '.join(extra)})" if extra else query


@app.post("/search")
def do_search(body: SearchRequest) -> dict:
    embedder, collection = _ready()
    pool = max(body.k * 4, 20)
    bm25 = _bm25()
    query = expand_query(body.query)
    vector_hits = [
        h for h in search(query, embedder, collection, k=pool, role=body.role)
        if h.document_id not in bm25.excluded_documents and not is_toc(h.text)
    ]
    # Catatan: BM25 belum memfilter peran. Aman selama semua dokumen "publik" (scope mahasiswa).
    keyword_hits = bm25.search(query, k=pool)
    return {"hits": [asdict(h) for h in fuse(vector_hits, keyword_hits, k=body.k)]}
