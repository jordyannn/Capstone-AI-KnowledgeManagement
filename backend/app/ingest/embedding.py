"""Embedding teks. Dependensi berat (torch, sentence-transformers) hanya ada di image worker,
jadi di-import saat model dimuat, bukan saat modul diimpor. Dengan begitu backend dan unit test
tidak membutuhkannya.
"""

from typing import Protocol


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class SentenceTransformerEmbedder:
    """Model keluarga e5 dilatih dengan awalan "passage: " / "query: " dan wajib memakainya.
    Model lain (mis. bge-m3) tidak memakai awalan; dideteksi dari nama model."""

    def __init__(self, model_name: str, batch_size: int = 32):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None
        is_e5 = "e5" in model_name.lower()
        self._passage_prefix = "passage: " if is_e5 else ""
        self._query_prefix = "query: " if is_e5 else ""

    def load(self) -> None:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)

    def _encode(self, texts: list[str]) -> list[list[float]]:
        self.load()
        # Vektor dinormalisasi agar jarak cosine di ChromaDB setara dengan 1 - kemiripan.
        vectors = self._model.encode(
            texts, batch_size=self.batch_size, normalize_embeddings=True, show_progress_bar=False
        )
        return vectors.tolist()

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self._passage_prefix + t for t in texts])

    def embed_query(self, text: str) -> list[float]:
        return self._encode([self._query_prefix + text])[0]
