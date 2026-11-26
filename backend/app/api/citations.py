"""Pemeriksaan sitasi setelah model menjawab.

Model kecil kadang menulis fakta yang benar tetapi menempelkan nomor sumber yang salah (contoh nyata
18 Nov: "60 poin [3]", padahal potongan [3] membahas remedial dan angka 60 ada di potongan lain).
Modul ini memeriksa tiap kalimat jawaban secara deterministik, tanpa memanggil model lagi:

1. Ambil "fakta kunci" kalimat itu, yaitu angka (60, 144, 2027, 10%).
2. Bila semua fakta ada di teks potongan yang dikutip kalimat itu, sitasi dibiarkan.
3. Bila tidak, cari potongan konteks yang memuat SEMUA fakta tersebut. Kalau ada, nomor sitasi kalimat
   itu diganti ke potongan tersebut (peringkat teratas). Kalau tidak ada, sitasi dibiarkan apa adanya
   (tidak bisa dipastikan, jadi tidak diubah).
4. Potongan berbeda dari dokumen + halaman yang sama digabung menjadi satu nomor, supaya daftar
   sumber tidak menampilkan "Pedoman Akademik hal. 51" dua kali.

Kalimat tanpa angka tidak diperiksa: mencocokkan kata secara longgar terlalu mudah salah.
"""

import re

_MARKER = re.compile(r"\[(\d+)\]")
# Angka sebagai token utuh: 60, 144, 2027, 3.00, 10. Tidak menangkap angka di dalam kata (mis. "S1").
_NUMBER = re.compile(r"(?<![\w.,])(\d+(?:[.,]\d+)?)(?![\w])")
# Batas kalimat: baris baru, atau titik/tanda tanya/seru diikuti spasi. Titik setelah angka TIDAK
# dihitung batas, supaya nomor daftar "1. Mahasiswa ..." tidak terpisah dari isinya.
_SENTENCE = re.compile(r"(?<=[^\d\s][.!?])[ \t]+|\n+")


def _numbers(text: str) -> set[str]:
    """Angka di teks, dinormalkan (koma desimal → titik). Nomor daftar "1." di awal baris diabaikan."""
    text = _MARKER.sub(" ", text)
    text = re.sub(r"^\s*\d+[.)]\s", " ", text)  # "1. Mahasiswa ..." → bukan fakta
    return {n.replace(",", ".") for n in _NUMBER.findall(text)}


def _supports(chunk_text: str, facts: set[str]) -> bool:
    found = _numbers(chunk_text)
    return facts <= found


def _distinctive(fact: str) -> bool:
    """Angka yang cukup khas untuk menunjuk sumber: ≥ 10 atau desimal (3.00)."""
    try:
        return "." in fact or float(fact) >= 10
    except ValueError:
        return False


_WORD = re.compile(r"[a-zA-Z]{3,}")
# Kata umum yang muncul di hampir semua potongan; tidak membedakan sumber.
_COMMON = {"yang", "dengan", "untuk", "dalam", "atau", "pada", "dari", "harus", "dapat", "tidak", "akan",
           "sebagai", "berikut", "adalah", "mahasiswa", "telkom", "universitas", "tersebut", "bagi", "oleh"}


def _words(text: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(text)} - _COMMON


def _overlap(sentence: str, chunk_text: str) -> int:
    return len(_words(sentence) & _words(chunk_text))


# Ambang untuk sitasi tanpa angka: sumber yang dikutip dianggap salah bila hampir tidak berbagi kata
# dengan kalimatnya, sementara ada potongan lain yang jelas lebih cocok.
_MIN_SHARED = 3


_ONLY_MARKERS = re.compile(r"\s*(\[\d+\]\s*)+[.!?]?\s*")


def _split(answer: str) -> tuple[list[str], list[str]]:
    """Pisah jawaban per kalimat. Potongan yang isinya hanya nomor sitasi (model sering menulis
    "... 2026. [2]") digabung ke kalimat sebelumnya, karena sitasi itu milik kalimat tersebut."""
    raw_parts = _SENTENCE.split(answer)
    raw_seps = _SENTENCE.findall(answer)
    parts, seps = [raw_parts[0]], []
    for sep, part in zip(raw_seps, raw_parts[1:]):
        if _ONLY_MARKERS.fullmatch(part) and "\n" not in sep:
            parts[-1] = parts[-1] + sep + part
        else:
            seps.append(sep)
            parts.append(part)
    return parts, seps


def _canonical(hits: list[dict]) -> dict[int, int]:
    """Nomor potongan → nomor pertama dengan judul + halaman yang sama."""
    first: dict[tuple[str, int], int] = {}
    out: dict[int, int] = {}
    for i, h in enumerate(hits, start=1):
        key = (h["title"], h["page_number"])
        first.setdefault(key, i)
        out[i] = first[key]
    return out


def fix_citations(answer: str, hits: list[dict]) -> tuple[str, list[int]]:
    """Kembalikan (jawaban dengan sitasi yang sudah diperiksa, nomor potongan yang dikutip, terurut).

    Nomor di luar jumlah potongan dibuang. Bila jawaban sama sekali tanpa sitasi, daftar kosong
    dikembalikan; pemanggil yang memutuskan fallback-nya.
    """
    valid = set(range(1, len(hits) + 1))
    canon = _canonical(hits)
    parts, seps = _split(answer)
    fixed_parts: list[str] = []
    cited: set[int] = set()

    for part in parts:
        raw = [int(n) for n in _MARKER.findall(part)]
        markers = [m for m in raw if m in valid]
        facts = _numbers(part)
        new_markers = markers
        if facts and markers:
            # Model mengutip sesuatu: pastikan angkanya ada di sana. Kalau tidak, pindah ke potongan yang
            # memuat angka itu DAN paling banyak berbagi kata dengan kalimatnya (angka kecil seperti "1"
            # atau "2" ada di hampir semua potongan, jadi angka saja tidak cukup untuk memilih).
            if not _supports(" ".join(hits[m - 1]["text"] for m in markers), facts):
                supporting = [i for i, h in enumerate(hits, start=1) if _supports(h["text"], facts)]
                if supporting:
                    new_markers = [max(supporting, key=lambda i: (_overlap(part, hits[i - 1]["text"]), -i))]
        elif markers:
            # Kalimat tanpa angka: ganti sumber hanya bila yang dikutip nyaris tidak berbagi kata dengan
            # kalimat, sementara potongan lain jelas lebih cocok (≥ 3 kata dan ≥ 2× lipat).
            current = max(_overlap(part, hits[m - 1]["text"]) for m in markers)
            best = max(range(1, len(hits) + 1), key=lambda i: (_overlap(part, hits[i - 1]["text"]), -i))
            best_score = _overlap(part, hits[best - 1]["text"])
            if best_score >= _MIN_SHARED and best_score >= 2 * max(current, 1):
                new_markers = [best]
        elif facts and any(_distinctive(f) for f in facts):
            # Kalimat TANPA sitasi dari model hanya ditambahi sumber bila memuat angka yang khas (≥ 10,
            # mis. "24 SKS", "10%"). Angka kecil seperti "1" dan "2" ada di hampir semua potongan:
            # 23 Nov, daftar syarat cuti sempat diberi sumber Kalender karena memuat "tingkat-1" dan "2 semester".
            supporting = [i for i, h in enumerate(hits, start=1) if _supports(h["text"], facts)]
            if supporting:
                new_markers = [max(supporting, key=lambda i: (_overlap(part, hits[i - 1]["text"]), -i))]
        new_markers = sorted({canon[m] for m in new_markers})
        cited.update(new_markers)
        # Kalimat ditulis ulang hanya bila sitasinya berubah (atau ada nomor tak valid). Kalau tidak,
        # posisi nomor di tengah kalimat dibiarkan seperti tulisan model.
        if new_markers != sorted(set(raw)) or len(raw) != len(set(raw)):
            body = re.sub(r"\s+([.!?])", r"\1", _MARKER.sub("", part)).rstrip()
            # Sitasi diletakkan sebelum tanda baca akhir kalimat bila ada: "... 60 poin [2]."
            tail = ""
            if body and body[-1] in ".!?:;":
                body, tail = body[:-1].rstrip(), body[-1]
            tags = "".join(f"[{m}]" for m in new_markers)
            part = f"{body} {tags}{tail}" if tags else f"{body}{tail}"
        fixed_parts.append(part)

    out = fixed_parts[0]
    for sep, part in zip(seps, fixed_parts[1:]):
        out += sep + part
    return out, sorted(cited)
