"""Pilihan model lokal/komersial (seperti proyek KP)."""

import json

from app import llm
from app.api import chat as chat_module
from app.core.config import get_settings
from tests.test_chat import FakeStream, hit, login, parse_sse


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def enable_groq(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "commercial_llm_enabled", True)
    monkeypatch.setattr(s, "groq_api_key", "test-key")


def recording_post(calls, answer="Jawaban [1]."):
    def _post(url, json=None, timeout=None, headers=None):
        calls.append((url, json, headers))
        if url.endswith("/search"):
            return FakeResponse({"hits": [hit(1)]})
        if "groq.com" in url:
            return FakeResponse({"choices": [{"message": {"content": answer}}]})
        return FakeResponse({"message": {"content": answer}})

    return _post


def test_bawaan_hanya_model_lokal(client, make_user):
    login(client, make_user)
    models = client.get("/api/chat/models").json()
    assert [m["code"] for m in models] == ["lokal"]


def test_komersial_muncul_hanya_bila_diaktifkan_dan_ada_key(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(get_settings(), "groq_api_key", "test-key")
    assert [m["code"] for m in client.get("/api/chat/models").json()] == ["lokal"]  # belum diaktifkan
    monkeypatch.setattr(get_settings(), "commercial_llm_enabled", True)
    assert [m["code"] for m in client.get("/api/chat/models").json()] == ["lokal", "groq"]


def test_pertanyaan_biasa_ke_groq(client, make_user, monkeypatch):
    login(client, make_user)
    enable_groq(monkeypatch)
    calls = []
    monkeypatch.setattr(chat_module.httpx, "post", recording_post(calls))
    body = client.post("/api/chat", json={"question": "berapa poin TAK?", "model": "groq"}).json()
    assert body["llm_used"].startswith("Groq") and body["llm_note"] is None
    llm_call = [c for c in calls if "groq.com" in c[0]][0]
    assert llm_call[2]["Authorization"] == "Bearer test-key"
    detail = client.get(f"/api/chat/conversations/{body['conversation_id']}").json()
    assert detail["messages"][-1]["llm_used"].startswith("Groq")


def test_pertanyaan_berdata_pribadi_dipaksa_lokal(client, make_user, monkeypatch):
    login(client, make_user)
    enable_groq(monkeypatch)
    calls = []
    monkeypatch.setattr(chat_module.httpx, "post", recording_post(calls))
    body = client.post("/api/chat", json={"question": "NIM saya 1202220123, cara cuti?", "model": "groq"}).json()
    assert body["llm_used"].startswith("Lokal") and "sensitif" in body["llm_note"]
    assert not any("groq.com" in c[0] for c in calls)


def test_kata_sensitif_dipaksa_lokal(client, make_user, monkeypatch):
    login(client, make_user)
    enable_groq(monkeypatch)
    calls = []
    monkeypatch.setattr(chat_module.httpx, "post", recording_post(calls))
    body = client.post("/api/chat", json={"question": "saya sakit lama, bisa cuti?", "model": "groq"}).json()
    assert body["llm_used"].startswith("Lokal")
    assert not any("groq.com" in c[0] for c in calls)


def test_model_tidak_tersedia_kembali_ke_lokal(client, make_user, monkeypatch):
    login(client, make_user)
    calls = []
    monkeypatch.setattr(chat_module.httpx, "post", recording_post(calls))
    body = client.post("/api/chat", json={"question": "poin TAK?", "model": "groq"}).json()
    assert body["llm_used"].startswith("Lokal") and body["llm_note"] == "model yang dipilih tidak tersedia"


def test_stream_groq_format_openai(client, make_user, monkeypatch):
    login(client, make_user)
    enable_groq(monkeypatch)
    monkeypatch.setattr(chat_module.httpx, "post", recording_post([]))
    lines = [
        "data: " + json.dumps({"choices": [{"delta": {"content": "Minimal 60 "}}]}),
        "",
        "data: " + json.dumps({"choices": [{"delta": {"content": "poin [1]."}}]}),
        "data: [DONE]",
    ]
    monkeypatch.setattr(chat_module.httpx, "stream", lambda *a, **k: FakeStream(lines))
    events = parse_sse(client.post("/api/chat/stream", json={"question": "poin TAK?", "model": "groq"}).text)
    done = events[-1][1]
    assert done["answer"] == "Minimal 60 poin [1]." and done["llm_used"].startswith("Groq")


def test_sitasi_gaya_gpt_oss_dinormalkan(client, make_user, monkeypatch):
    login(client, make_user)
    enable_groq(monkeypatch)
    monkeypatch.setattr(chat_module.httpx, "post", recording_post([], answer="Minimal **60 poin**【1†Nota】."))
    body = client.post("/api/chat", json={"question": "poin TAK?", "model": "groq"}).json()
    assert body["answer"] == "Minimal 60 poin [1]."
    assert [s["number"] for s in body["sources"]] == [1]


def test_kuota_cloud_habis_dialihkan_ke_lokal(client, make_user, monkeypatch):
    import httpx as real_httpx

    login(client, make_user)
    enable_groq(monkeypatch)
    calls = []

    def _post(url, json=None, timeout=None, headers=None):
        calls.append(url)
        if url.endswith("/search"):
            return FakeResponse({"hits": [hit(1)]})
        if "groq.com" in url:
            req = real_httpx.Request("POST", url)
            raise real_httpx.HTTPStatusError("429", request=req, response=real_httpx.Response(429, request=req))
        return FakeResponse({"message": {"content": "Jawaban lokal [1]."}})

    monkeypatch.setattr(chat_module.httpx, "post", _post)
    body = client.post("/api/chat", json={"question": "poin TAK?", "model": "groq"}).json()
    assert body["answer"] == "Jawaban lokal [1]."
    assert body["llm_used"].startswith("Lokal") and "batas kuota" in body["llm_note"]


def test_stream_kuota_cloud_habis_dialihkan_ke_lokal(client, make_user, monkeypatch):
    import httpx as real_httpx
    from tests.test_chat import ollama_lines

    login(client, make_user)
    enable_groq(monkeypatch)
    monkeypatch.setattr(chat_module.httpx, "post", recording_post([]))

    class Limited:
        def __enter__(self):
            req = real_httpx.Request("POST", "https://api.groq.com")
            raise real_httpx.HTTPStatusError("429", request=req, response=real_httpx.Response(429, request=req))

        def __exit__(self, *a):
            return False

    def _stream(method, url, json=None, timeout=None, headers=None):
        return Limited() if "groq.com" in url else FakeStream(ollama_lines("Jawaban lokal [1]."))

    monkeypatch.setattr(chat_module.httpx, "stream", _stream)
    events = parse_sse(client.post("/api/chat/stream", json={"question": "poin TAK?", "model": "groq"}).text)
    done = events[-1][1]
    assert done["answer"] == "Jawaban lokal [1]." and done["llm_used"].startswith("Lokal")
    assert "batas kuota" in done["llm_note"]


def test_choose_hanya_bisa_memindah_ke_lokal(monkeypatch):
    enable_groq(monkeypatch)
    p, note = llm.choose("groq", "jadwal wisuda?", [])
    assert p.code == "groq" and note is None
    p, note = llm.choose("lokal", "jadwal wisuda?", [])
    assert p.code == "lokal"
