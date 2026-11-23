"""Penyamaran data pribadi (F-14, UU No. 27/2022 tentang Pelindungan Data Pribadi).

Dipakai di dua tempat:
- pesan mahasiswa di chat AI, sebelum dicari, dikirim ke model bahasa, dan disimpan sebagai riwayat;
- teks dokumen saat di-index (mode "dokumen", lebih sempit), supaya data pribadi di dokumen (mis. NIK
  pegawai di nota dinas) tidak ikut masuk konteks model dan cuplikan sumber.

Berbasis pola (regex), jadi yang disamarkan adalah data berformat jelas: surel, nomor telepon,
nomor identitas berlabel (NIM/NIK/NIP/NIDN/NPWP), dan deret angka panjang (9–20 digit) yang hampir
pasti nomor identitas atau rekening. NAMA ORANG TIDAK DISAMARKAN: butuh model NER, dan nama pejabat
di dokumen resmi memang informasi publik. Ini dicatat sebagai keterbatasan.

Tidak dipakai di livechat/tiket: mahasiswa kadang memang perlu menyebut NIM kepada staf.
"""

import re

PESAN = "pesan"
DOKUMEN = "dokumen"

# (label, pola, dipakai juga untuk dokumen?). Urutan penting: pola yang lebih spesifik lebih dulu.
# Untuk dokumen hanya nomor identitas berlabel dan jejak "Printed by": telepon dan surel di dokumen
# resmi adalah kontak layanan publik (mis. WA prodi) yang justru perlu bisa dijawab, dan deret angka
# panjang di dokumen bisa berupa nomor rekening pembayaran resmi.
_PATTERNS: list[tuple[str, re.Pattern, bool]] = [
    ("SUREL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), False),
    # Nomor identitas berlabel, berapa pun panjangnya: "NIK: 20820005", "NIM 1202220123".
    ("NOMOR_IDENTITAS", re.compile(r"(?i)\b(?:NIM|NIK|NIP|NIDN|NPWP|NIS|NISN)\b\s*[:.]?\s*\d[\d.\- ]{4,}\d"), True),
    # Telepon Indonesia: +62 / 62 / 08…, boleh dipisah spasi atau tanda hubung.
    ("TELEPON", re.compile(r"(?<!\d)(?:\+62|62|0)8\d(?:[\s-]?\d){6,11}(?!\d)"), False),
    # Deret angka panjang tanpa label (NIM, NIK 16 digit, rekening). Tahun, SKS, dan tanggal
    # (≤ 8 digit) tidak kena.
    # Batas: bukan bagian dari angka yang lebih panjang atau desimal ("1.234567890"), tetapi boleh
    # diikuti tanda baca kalimat ("NIM 1202220123, ...").
    ("NOMOR_IDENTITAS", re.compile(r"(?<![\d/])(?<!\d[.,])\d{9,20}(?![\d/])(?![.,]\d)"), False),
    # Jejak cetak di dokumen internal: "Printed by : NAMA/NIK".
    ("DICETAK_OLEH", re.compile(r"(?i)printed by\s*:\s*[^\n]+"), True),
]


def mask(text: str, kind: str = PESAN) -> tuple[str, list[str]]:
    """Kembalikan (teks tersamar, jenis data yang ditemukan). Placeholder: [SUREL], [TELEPON], ..."""
    found: list[str] = []
    for label, pattern, for_document in _PATTERNS:
        if kind == DOKUMEN and not for_document:
            continue
        text, n = pattern.subn(f"[{label}]", text)
        if n:
            found.append(label)
    return text, sorted(set(found))
