"""Riwayat percakapan (F-11) dan isolasi data antar mahasiswa."""

from app.api import chat as chat_module
from tests.conftest import PASSWORD
from tests.test_chat import FakeStream, fake_post, hit, ollama_lines, parse_sse


def login_as(client, make_user, email):
    make_user(email=email, role="mahasiswa")
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def test_chat_disimpan_dan_bisa_dilanjutkan(client, make_user, monkeypatch):
    login_as(client, make_user, "a@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1), hit(2)], "Syaratnya 144 SKS [2]."))

    first = client.post("/api/chat", json={"question": "Apa syarat sidang TA?"}).json()
    cid = first["conversation_id"]
    assert cid and first["message_id"]

    second = client.post("/api/chat", json={"question": "Kalau KPPM?", "conversation_id": cid}).json()
    assert second["conversation_id"] == cid

    convs = client.get("/api/chat/conversations").json()
    assert [c["id"] for c in convs] == [cid]
    assert convs[0]["title"] == "Apa syarat sidang TA?"

    detail = client.get(f"/api/chat/conversations/{cid}").json()
    assert [m["sender"] for m in detail["messages"]] == ["mahasiswa", "asisten", "mahasiswa", "asisten"]
    assert detail["messages"][1]["sources"][0]["number"] == 2


def test_eskalasi_juga_disimpan(client, make_user, monkeypatch):
    login_as(client, make_user, "a@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1, score=0.5)], ""))
    body = client.post("/api/chat", json={"question": "resep rendang?"}).json()
    detail = client.get(f"/api/chat/conversations/{body['conversation_id']}").json()
    assert detail["messages"][-1]["escalated"] is True


def test_stream_menyimpan_jawaban(client, make_user, monkeypatch):
    login_as(client, make_user, "a@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], ""))
    monkeypatch.setattr(chat_module.httpx, "stream", lambda *a, **k: FakeStream(ollama_lines("Jawabannya 60 poin [1].")))
    events = parse_sse(client.post("/api/chat/stream", json={"question": "poin TAK?"}).text)
    done = events[-1][1]
    detail = client.get(f"/api/chat/conversations/{done['conversation_id']}").json()
    assert detail["messages"][-1]["content"] == "Jawabannya 60 poin [1]."
    assert detail["messages"][-1]["id"] == done["message_id"]


def test_mahasiswa_lain_tidak_bisa_membaca_atau_melanjutkan(client, make_user, monkeypatch):
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], "Jawaban [1]."))
    login_as(client, make_user, "a@example.test")
    cid = client.post("/api/chat", json={"question": "rahasia A"}).json()["conversation_id"]

    login_as(client, make_user, "b@example.test")
    assert client.get("/api/chat/conversations").json() == []
    assert client.get(f"/api/chat/conversations/{cid}").status_code == 404
    assert client.post("/api/chat", json={"question": "ikut", "conversation_id": cid}).status_code == 404
    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 404


def test_hapus_percakapan(client, make_user, monkeypatch):
    login_as(client, make_user, "a@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], "Jawaban [1]."))
    cid = client.post("/api/chat", json={"question": "halo"}).json()["conversation_id"]
    assert client.delete(f"/api/chat/conversations/{cid}").status_code == 204
    assert client.get("/api/chat/conversations").json() == []
