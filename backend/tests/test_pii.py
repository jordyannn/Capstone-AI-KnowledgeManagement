"""Penyamaran data pribadi (F-14)."""

from app.api import chat as chat_module
from app.core.pii import DOKUMEN, mask
from tests.test_chat import FakeStream, fake_post, hit, login, ollama_lines, parse_sse


def test_pesan_nim_telepon_surel_disamarkan():
    text, found = mask("NIM saya 1202220123, WA 0812-3456-7890, surel budi.s@student.telkomuniversity.ac.id")
    assert "1202220123" not in text and "0812" not in text and "budi.s@" not in text
    assert "[NOMOR_IDENTITAS]" in text and "[TELEPON]" in text and "[SUREL]" in text
    assert found == ["NOMOR_IDENTITAS", "SUREL", "TELEPON"]


def test_nomor_identitas_berlabel_berapa_pun_panjangnya():
    text, _ = mask("NIK: 20820005 dan NIP 123456")
    assert text == "[NOMOR_IDENTITAS] dan [NOMOR_IDENTITAS]"


def test_angka_biasa_tidak_kena():
    original = "Minimal 144 SKS, TAK 60 poin, batas 29 Januari 2027, IPK 3.00, biaya 10%, ND.7131/PD01/YPT-TUN/2026"
    text, found = mask(original)
    assert text == original and found == []


def test_mode_dokumen_hanya_identitas_berlabel_dan_jejak_cetak():
    doc = "Hubungi WA prodi +62 822-5856-9083 atau sisfor@telkomuniversity.ac.id\nNIK: 20820005\nPrinted by : DWINA SATRINIA/25890015"
    text, found = mask(doc, kind=DOKUMEN)
    # Kontak layanan resmi tetap ada (pertanyaan web-01 di set uji butuh nomor WA prodi).
    assert "+62 822-5856-9083" in text and "sisfor@telkomuniversity.ac.id" in text
    assert "20820005" not in text and "DWINA" not in text and "25890015" not in text
    assert found == ["DICETAK_OLEH", "NOMOR_IDENTITAS"]


def test_chat_menyamarkan_pertanyaan_sebelum_ke_model_dan_riwayat(client, make_user, monkeypatch):
    login(client, make_user)
    seen = {}

    def _post(url, json, timeout):
        seen.setdefault("calls", []).append(json)
        return fake_post([hit(1)], "Jawaban [1].")(url, json, timeout)

    monkeypatch.setattr(chat_module.httpx, "post", _post)
    body = client.post("/api/chat", json={"question": "NIM saya 1202220123, kapan batas KRS?"}).json()
    assert body["masked"] == ["NOMOR_IDENTITAS"]
    # Tidak ada permintaan (pencarian maupun model) yang membawa NIM asli.
    assert all("1202220123" not in str(c) for c in seen["calls"])
    detail = client.get(f"/api/chat/conversations/{body['conversation_id']}").json()
    assert "1202220123" not in detail["title"]
    assert detail["messages"][0]["content"] == "NIM saya [NOMOR_IDENTITAS], kapan batas KRS?"


def test_stream_juga_menyamarkan(client, make_user, monkeypatch):
    login(client, make_user)
    sent = []
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], ""))

    def _stream(method, url, json, timeout):
        sent.append(json)
        return FakeStream(ollama_lines("Jawaban [1]."))

    monkeypatch.setattr(chat_module.httpx, "stream", _stream)
    events = parse_sse(client.post("/api/chat/stream", json={"question": "HP saya 081234567890, cara cuti?"}).text)
    assert events[-1][1]["masked"] == ["TELEPON"]
    assert "081234567890" not in str(sent)
