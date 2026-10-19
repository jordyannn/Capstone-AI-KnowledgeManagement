"""Memotong teks halaman menjadi chunk untuk embedding.

Invarian yang dijamin (dan diuji): untuk setiap chunk, text == page_text[char_start:char_end].
"""

from dataclasses import dataclass

TARGET_CHARS = 1000  # batas bawah ideal; potongan dicari di antara TARGET dan MAX
MAX_CHARS = 1500
OVERLAP_CHARS = 200

# Urutan preferensi tempat memotong: paragraf > baris > akhir kalimat > spasi.
_BOUNDARIES = ("\n\n", "\n", ". ", "? ", "! ", "; ", ", ", " ")


@dataclass(frozen=True)
class TextChunk:
    index: int
    text: str
    char_start: int
    char_end: int

    @property
    def token_estimate(self) -> int:
        # Perkiraan kasar ~4 karakter per token; hanya untuk statistik, bukan batas keras.
        return max(1, -(-len(self.text) // 4))


def _find_end(text: str, start: int, target: int, max_chars: int) -> int:
    """Cari titik akhir chunk di (start+target, start+max_chars], di batas alami terbaik."""
    hard_end = min(start + max_chars, len(text))
    if hard_end >= len(text):
        return len(text)
    window_lo = start + target
    for sep in _BOUNDARIES:
        pos = text.rfind(sep, window_lo, hard_end)
        if pos != -1:
            return pos + len(sep)
    return hard_end  # tidak ada batas alami: potong keras


def _skip_whitespace(text: str, pos: int) -> int:
    while pos < len(text) and text[pos].isspace():
        pos += 1
    return pos


def _word_start(text: str, pos: int, limit: int) -> int:
    """Geser pos maju ke awal kata berikutnya supaya chunk tidak dimulai di tengah kata."""
    if pos <= 0 or pos >= len(text) or text[pos - 1].isspace():
        return pos
    scan = pos
    while scan < limit and not text[scan].isspace():
        scan += 1
    return _skip_whitespace(text, scan) if scan < limit else pos


def chunk_text(
    text: str,
    target: int = TARGET_CHARS,
    max_chars: int = MAX_CHARS,
    overlap: int = OVERLAP_CHARS,
) -> list[TextChunk]:
    if not (0 <= overlap < target <= max_chars):
        raise ValueError("Harus 0 <= overlap < target <= max_chars.")

    chunks: list[TextChunk] = []
    start = _skip_whitespace(text, 0)
    while start < len(text):
        end = _find_end(text, start, target, max_chars)
        piece_end = end
        while piece_end > start and text[piece_end - 1].isspace():
            piece_end -= 1
        if piece_end > start:
            chunks.append(TextChunk(len(chunks), text[start:piece_end], start, piece_end))
        if end >= len(text):
            break
        # Mundur sebesar overlap, tetapi selalu maju dibanding chunk sebelumnya.
        next_start = _word_start(text, max(end - overlap, start + 1), end)
        start = _skip_whitespace(text, max(next_start, start + 1))
    return chunks
