"""Pemantauan sederhana (UC-07, SCRUM-80)."""

from app.api import chat as chat_module
from tests.test_chat import fake_post, hit
from tests.test_support import login, new_request


def test_angka_ringkas_hanya_dari_mahasiswa(client, make_user, monkeypatch):
    make_user(email="a@example.test", role="mahasiswa")
    make_user(email="b@example.test", role="mahasiswa")
    make_user(email="admin@example.test", role="admin")

    login(client, "a@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], "Jawaban [1]."))
    client.post("/api/chat", json={"question": "syarat sidang?"})
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1, score=0.5)], ""))
    client.post("/api/chat", json={"question": "resep rendang?"})  # dieskalasi
    rid = new_request(client)["id"]

    login(client, "b@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], "Jawaban [1]."))
    client.post("/api/chat", json={"question": "poin TAK?"})

    login(client, "admin@example.test")
    client.post("/api/chat", json={"question": "uji admin, tidak dihitung"})
    client.post(f"/api/admin/support/requests/{rid}/messages", json={"content": "Halo"})

    s = client.get("/api/admin/stats").json()
    assert s["questions"] == 3 and s["students"] == 2
    assert s["answered"] == 2 and s["escalated"] == 1 and s["escalated_pct"] == 33.3
    assert s["support_active"] == 1 and s["support_ticket"] == 1
    assert s["by_category"] == {"akademik": 1}
    assert s["first_reply_median_minutes"] is not None
    assert sum(d["questions"] for d in s["per_day"]) == 3


def test_stats_hanya_untuk_staf(client, make_user):
    make_user(email="a@example.test", role="mahasiswa")
    login(client, "a@example.test")
    assert client.get("/api/admin/stats").status_code == 403
