"""Pemeriksaan sitasi pasca-jawaban (app/api/citations.py)."""

from app.api import chat as chat_module
from app.api.citations import fix_citations
from tests.test_chat import fake_post, login


def h(title, page, text):
    return {"title": title, "page_number": page, "text": text, "score": 0.9, "source_url": ""}


KURIKULUM = h("Buku Kurikulum", 49, "Proses remedial: jika nilai CLO di bawah nilai minimum, mahasiswa mengulang.")
NOTA_TAK = h("Nota Dinas TAK 2026", 1, "Standar Nilai Minimal TAK Sarjana/D4 Reguler : 60 poin Diploma 3 : 45 poin")
PANDUAN_TA = h("Panduan TA", 16, "Jumlah poin TAK minimal 60 poin dan maksimal 120 poin")


def test_sitasi_salah_dipindah_ke_potongan_yang_memuat_angka():
    # Kasus nyata 18 Nov: angka benar, nomor sumber menunjuk halaman remedial.
    answer, cited = fix_citations("60 poin [3]", [NOTA_TAK, PANDUAN_TA, KURIKULUM])
    assert answer == "60 poin [1]"
    assert cited == [1]


def test_sitasi_benar_tidak_diubah_termasuk_posisinya():
    text = "Minimal TAK sarjana reguler [1] adalah 60 poin."
    answer, cited = fix_citations(text, [NOTA_TAK, KURIKULUM])
    assert answer == text
    assert cited == [1]


def test_tidak_ada_potongan_yang_memuat_angka_maka_sitasi_dibiarkan():
    answer, cited = fix_citations("Batasnya 99 hari [2].", [NOTA_TAK, KURIKULUM])
    assert answer == "Batasnya 99 hari [2]."
    assert cited == [2]


def test_kalimat_tanpa_angka_tidak_diperiksa():
    answer, cited = fix_citations("Permohonan disetujui dosen wali [2].", [NOTA_TAK, KURIKULUM])
    assert cited == [2]


def test_potongan_dobel_dari_halaman_sama_digabung():
    p1 = h("Pedoman Akademik 2026", 51, "Cuti akademik dibatasi maksimal 2 (dua) semester.")
    p2 = h("Pedoman Akademik 2026", 51, "Permohonan diajukan paling lambat di masa PRS.")
    answer, cited = fix_citations("Cuti maksimal 2 semester [1][2].\nDiajukan saat PRS [2].", [p1, p2])
    assert cited == [1]
    assert answer == "Cuti maksimal 2 semester [1].\nDiajukan saat PRS [1]."


def test_nomor_di_luar_konteks_dibuang():
    answer, cited = fix_citations("Syaratnya lulus [9].", [NOTA_TAK])
    assert "[9]" not in answer and cited == []


def test_nomor_daftar_bukan_fakta():
    p = h("Pedoman Akademik 2026", 51, "Cuti akademik dibatasi maksimal 2 (dua) semester.")
    answer, cited = fix_citations("1. Cuti maksimal 2 semester [1].", [p])
    assert answer == "1. Cuti maksimal 2 semester [1]."
    assert cited == [1]


def test_daftar_bernomor_tetap_utuh():
    # Regresi 22 Nov: "1." sempat dipotong jadi kalimat sendiri lalu ditempeli sitasi ("1 [1].").
    p = h("Pedoman Akademik 2026", 51, "Permohonan diajukan paling lambat di masa PRS. Cuti maksimal 2 semester.")
    text = "Caranya:\n\n1. Ajukan paling lambat masa PRS [1].\n2. Cuti maksimal 2 semester [1]."
    answer, cited = fix_citations(text, [KURIKULUM, p])
    # Butir 1 tanpa angka: [1] (remedial) tidak berbagi kata, [2] berbagi "paling", "lambat", "masa".
    assert answer == "Caranya:\n\n1. Ajukan paling lambat masa PRS [2].\n2. Cuti maksimal 2 semester [2]."
    assert cited == [2]


def test_kalimat_tanpa_sitasi_tidak_ditambahi_sumber():
    # Regresi 23 Nov: daftar syarat cuti tanpa sitasi diberi sumber Kalender karena memuat "1" dan "2".
    kalender = h("Kalender Pendidikan 2026", 1, "Senin 1 2 3 Rencana Studi Semester 2025-2")
    pedoman = h("Pedoman Akademik 2026", 51, "Cuti akademik dibatasi maksimal 2 (dua) semester, tingkat-1.")
    text = "1. Cuti tidak boleh sebelum tingkat-1.\n2. Cuti maksimal 2 semester."
    answer, cited = fix_citations(text, [kalender, pedoman])
    assert answer == text and cited == []


def test_kalimat_tanpa_sitasi_dengan_angka_khas_diberi_sumber():
    p20 = h("Pedoman Akademik 2026", 20, "Beban studi maksimal 24 SKS per semester untuk IPK di atas 3.00")
    answer, cited = fix_citations("24 SKS", [KURIKULUM, p20])
    assert answer == "24 SKS [2]" and cited == [2]


def test_angka_kecil_dipindah_ke_potongan_yang_berbagi_kata():
    kalender = h("Kalender Pendidikan 2026", 1, "Senin 1 2 3 Rencana Studi Semester 2025-2")
    pedoman = h("Pedoman Akademik 2026", 51, "Cuti akademik dibatasi maksimal 2 (dua) semester selama masa studi.")
    nota = h("Nota", 1, "tidak relevan")
    answer, cited = fix_citations("Cuti akademik maksimal 2 semester selama masa studi [3].", [kalender, pedoman, nota])
    assert answer == "Cuti akademik maksimal 2 semester selama masa studi [2]." and cited == [2]


def test_sitasi_setelah_titik_ikut_kalimat_sebelumnya():
    # Model sering menulis "... 2026. [2]": nomor itu milik kalimat sebelumnya.
    p = h("Kalender", 6, "Wisuda I Tahun Akademik 2026/2027 27 - 28 November 2026")
    answer, cited = fix_citations("Wisuda I pada 27 - 28 November 2026. [2]", [KURIKULUM, p])
    assert cited == [2]
    answer, cited = fix_citations("Satu SKS setara 45 jam [2]. [2][2]", [KURIKULUM, h("Pedoman", 18, "1 SKS setara 45 jam")])
    assert answer == "Satu SKS setara 45 jam [2]." and cited == [2]


def test_endpoint_memakai_sitasi_yang_sudah_diperbaiki(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([NOTA_TAK, PANDUAN_TA, KURIKULUM], "Minimal 60 poin [3]."))
    body = client.post("/api/chat", json={"question": "poin TAK minimal?"}).json()
    assert body["answer"] == "Minimal 60 poin [1]."
    assert [(s["number"], s["title"]) for s in body["sources"]] == [(1, "Nota Dinas TAK 2026")]
