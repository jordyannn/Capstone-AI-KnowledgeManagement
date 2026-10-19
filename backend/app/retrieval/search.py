from dataclasses import dataclass

from app.ingest.embedding import Embedder
from app.retrieval.access import build_role_where


@dataclass(frozen=True)
class Hit:
    score: float  # kemiripan cosine, 1.0 = identik
    title: str
    source_url: str
    page_number: int
    chunk_index: int
    document_id: str
    allowed_roles: str
    text: str


def search(query: str, embedder: Embedder, collection, k: int = 5, role: str | None = None) -> list[Hit]:
    """Top-k chunk paling mirip, hanya dari dokumen yang boleh dibaca `role`.
    Filter akses diterapkan di ChromaDB (bukan setelah hasil diambil), supaya k tetap terisi."""
    result = collection.query(
        query_embeddings=[embedder.embed_query(query)],
        n_results=k,
        where=build_role_where(role),
        include=["documents", "metadatas", "distances"],
    )
    hits = []
    for text, meta, distance in zip(result["documents"][0], result["metadatas"][0], result["distances"][0]):
        hits.append(
            Hit(
                score=1.0 - distance,
                title=meta.get("title", ""),
                source_url=meta.get("source_url", ""),
                page_number=meta.get("page_number", 0),
                chunk_index=meta.get("chunk_index", 0),
                document_id=meta.get("document_id", ""),
                allowed_roles=meta.get("allowed_roles", ""),
                text=text,
            )
        )
    return hits
