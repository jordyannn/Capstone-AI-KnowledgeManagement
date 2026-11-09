"""Hybrid retrieval: vektor (e5) + BM25 kata kunci, digabung dengan Reciprocal Rank Fusion (RRF).

Alasan: pada korpus berbahasa Indonesia, skor e5-small terkompresi (0,82–0,88) dan kalah untuk
pertanyaan yang bergantung pada istilah spesifik ("TAK", "sempro", "BPP"). Eksperimen Retrieval
(19 Okt 2026) menunjukkan hybrid BM25 + judul menaikkan top-1 15 -> 18 dari 20 pertanyaan.
BM25 ditulis tanpa dependensi tambahan supaya image worker tidak perlu dibangun ulang.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

from app.retrieval.search import Hit

_TOKEN = re.compile(r"[a-z0-9]+")
# Kata fungsi bahasa Indonesia yang tidak membantu pencarian.
_STOP = set(
    "yang dan di ke dari untuk pada dengan atau ini itu adalah dalam akan apa bagaimana berapa kapan siapa "
    "saya kami anda tidak bisa dapat harus ada oleh sebagai juga serta para tersebut agar bila jika".split()
)


# Kategori yang di luar cakupan layanan mahasiswa aktif (ADR-003): info penerimaan mahasiswa baru.
EXCLUDED_CATEGORIES = {"pmb"}


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP and len(t) > 1]


@dataclass
class _Doc:
    hit: Hit
    tf: Counter
    length: int


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs: list[_Doc] = []
        self.df: Counter = Counter()
        self.avgdl = 0.0
        self.excluded_documents: set[str] = set()  # dipakai juga untuk menyaring hasil vektor

    @classmethod
    def from_collection(cls, collection) -> "BM25Index":
        index = cls()
        data = collection.get(include=["documents", "metadatas"])
        for text, meta in zip(data["documents"], data["metadatas"]):
            if meta.get("category") in EXCLUDED_CATEGORIES:
                index.excluded_documents.add(meta.get("document_id", ""))
                continue
            hit = Hit(
                score=0.0,
                title=meta.get("title", ""),
                source_url=meta.get("source_url", ""),
                page_number=meta.get("page_number", 0),
                chunk_index=meta.get("chunk_index", 0),
                document_id=meta.get("document_id", ""),
                allowed_roles=meta.get("allowed_roles", ""),
                text=text,
            )
            # Judul ikut diindeks, sama seperti teks embedding.
            tokens = tokenize(f"{hit.title} {text}")
            tf = Counter(tokens)
            index.docs.append(_Doc(hit, tf, len(tokens)))
            index.df.update(tf.keys())
        index.avgdl = sum(d.length for d in index.docs) / max(len(index.docs), 1)
        return index

    def search(self, query: str, k: int) -> list[Hit]:
        terms = tokenize(query)
        n = len(self.docs)
        scored = []
        for d in self.docs:
            s = 0.0
            for t in terms:
                f = d.tf.get(t)
                if not f:
                    continue
                idf = math.log(1 + (n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * d.length / self.avgdl))
            if s > 0:
                scored.append((s, d.hit))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in scored[:k]]


def _key(h: Hit) -> tuple:
    return (h.document_id, h.page_number, h.chunk_index)



def fuse(vector_hits: list[Hit], bm25_hits: list[Hit], k: int) -> list[Hit]:
    """Gabungan berselang-seling (vektor, BM25, vektor, ...) tanpa duplikat.

    RRF murni diuji dulu, tetapi selalu memenangkan potongan yang muncul di kedua daftar meski
    tidak relevan, sehingga potongan BM25 peringkat 1 yang tepat (mis. nota dinas TAK) terdorong
    keluar. Berselang-seling menjamin kedua sumber mendapat tempat di konteks LLM.
    Skor yang dikembalikan tetap skor cosine (0 bila hanya dari BM25)."""
    out: list[Hit] = []
    seen: set[tuple] = set()
    for pair in zip(vector_hits + [None] * len(bm25_hits), bm25_hits + [None] * len(vector_hits)):
        for h in pair:
            if h is None or _key(h) in seen:
                continue
            seen.add(_key(h))
            out.append(h)
            if len(out) == k:
                return out
    return out
