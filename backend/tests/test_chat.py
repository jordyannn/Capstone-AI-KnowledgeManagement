import json

import httpx

from app.api import chat as chat_module
from tests.conftest import PASSWORD


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


def hit(n, score=0.9):
    return {
        "score": score,
        "title": f"Dokumen {n}",
        "source_url": "",
        "page_number": n,
        "chunk_index": 0,
        "document_id": str(n),
        "allowed_roles": "publik",
        "text": f"isi {n}",
    }


def fake_post(hits, answer):
    def _post(url, json, timeout):
        if url.endswith("/search"):
            return FakeResponse({"hits": hits})
        return FakeResponse({"message": {"content": answer}})

    return _post


def login(client, make_user):
    make_user(role="mahasiswa")
    client.post("/api/auth/login", json={"email": "dosen@example.test", "password": PASSWORD})


def test_chat_requires_login(client):
    assert client.post("/api/chat", json={"question": "syarat sempro?"}).status_code == 401


def test_chat_returns_only_cited_sources(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1), hit(2), hit(3)], "Syaratnya X [2]."))
    r = client.post("/api/chat", json={"question": "syarat sempro?"})
    assert r.status_code == 200
    body = r.json()
    assert body["escalate"] is False
    assert [s["number"] for s in body["sources"]] == [2]
    assert body["sources"][0]["page"] == 2


def test_chat_escalates_when_no_relevant_chunk(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1, score=0.5)], "tidak dipakai"))
    body = client.post("/api/chat", json={"question": "resep rendang?"}).json()
    assert body["escalate"] is True and body["sources"] == []


def test_chat_escalates_when_model_says_not_found(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], "TIDAK_DITEMUKAN"))
    body = client.post("/api/chat", json={"question": "jadwal kuliah saya?"}).json()
    assert body["escalate"] is True


class FakeStream:
    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        pass

    def iter_lines(self):
        yield from self.lines


def ollama_lines(*pieces):
    out = [json.dumps({"message": {"content": p}, "done": False}) for p in pieces]
    out.append(json.dumps({"message": {"content": ""}, "done": True}))
    return out


def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(l.split(": ", 1) for l in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def test_chat_stream_sends_tokens_then_done(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1), hit(2)], ""))
    monkeypatch.setattr(
        chat_module.httpx, "stream", lambda *a, **k: FakeStream(ollama_lines("Syarat sidang adalah ", "lulus 144 SKS [2]."))
    )
    r = client.post("/api/chat/stream", json={"question": "syarat sidang?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert "".join(e[1]["text"] for e in events if e[0] == "token") == "Syarat sidang adalah lulus 144 SKS [2]."
    kind, done = events[-1]
    assert kind == "done" and done["escalate"] is False and [s["number"] for s in done["sources"]] == [2]


def test_chat_stream_hides_not_found_and_escalates(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], ""))
    monkeypatch.setattr(chat_module.httpx, "stream", lambda *a, **k: FakeStream(ollama_lines("TIDAK_", "DITEMUKAN")))
    events = parse_sse(client.post("/api/chat/stream", json={"question": "resep rendang?"}).text)
    assert [e[0] for e in events] == ["done"]
    assert events[0][1]["escalate"] is True


def test_chat_stream_low_score_escalates_without_llm(client, make_user, monkeypatch):
    login(client, make_user)
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1, score=0.5)], ""))

    def no_llm(*a, **k):
        raise AssertionError("LLM tidak boleh dipanggil")

    monkeypatch.setattr(chat_module.httpx, "stream", no_llm)
    events = parse_sse(client.post("/api/chat/stream", json={"question": "cuaca besok?"}).text)
    assert len(events) == 1 and events[0][0] == "done" and events[0][1]["escalate"] is True


def test_chat_503_when_retrieval_down(client, make_user, monkeypatch):
    login(client, make_user)

    def boom(*args, **kwargs):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(chat_module.httpx, "post", boom)
    assert client.post("/api/chat", json={"question": "syarat sempro?"}).status_code == 503
