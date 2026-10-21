from app.core.config import Settings, get_settings
from app.models import Chunk, Document
from app.retrieval.access import role_flags


def get_collection(settings: Settings | None = None):
    """Collection tunggal untuk semua chunk, jarak cosine. Dibuat bila belum ada."""
    import chromadb

    settings = settings or get_settings()
    client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    return client.get_or_create_collection(
        name=settings.chroma_collection,
        configuration={"hnsw": {"space": "cosine"}},
        embedding_function=None,  # vektor selalu dihitung sendiri oleh Embedder
    )


def chunk_metadata(document: Document, chunk: Chunk) -> dict:
    """Metadata Chroma per chunk. Chroma menolak None dan list, jadi nilai kosong jadi "" dan
    daftar peran dipecah menjadi flag boolean (lihat retrieval/access.py)."""
    metadata = {
        "document_id": str(document.id),
        "chunk_id": str(chunk.id),
        "title": document.title,
        "source_url": document.source_url or "",
        "category": document.category or "",
        "tier": document.tier or "",
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "allowed_roles": ",".join(document.allowed_roles),
        **role_flags(document.allowed_roles),
    }
    if document.published_at:
        metadata["published_at"] = document.published_at.isoformat()
    return metadata
