"""Eskalasi ke staf (F-10): livechat/tiket, antrean admin, status online, dan isolasi data."""

from datetime import datetime, timedelta, timezone

from app.api import chat as chat_module
from app.models import StaffPresence
from tests.conftest import PASSWORD
from tests.test_chat import fake_post, hit


def login(client, email):
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": email, "password": PASSWORD}).status_code == 200


def go_online(client, make_user, email="staf@example.test", role="staf"):
    make_user(email=email, role=role)
    login(client, email)
    assert client.put("/api/admin/support/presence", json={"online": True}).json()["online"] is True


def new_request(client, **extra):
    body = {"category": "akademik", "message": "Kapan batas yudisium?\n\nJawaban AI: tidak ditemukan.", **extra}
    r = client.post("/api/support/requests", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_tanpa_staf_online_menjadi_tiket_menunggu(client, make_user):
    make_user(email="mhs@example.test", role="mahasiswa")
    login(client, "mhs@example.test")
    assert client.get("/api/support/status").json() == {"staff_online": False}

    req = new_request(client)
    assert req["kind"] == "tiket"
    assert req["status"] == "menunggu"
    assert req["subject"] == "Kapan batas yudisium?"
    assert [m["sender_role"] for m in req["messages"]] == ["mahasiswa"]


def test_staf_online_menjadi_livechat(client, make_user):
    go_online(client, make_user)
    make_user(email="mhs@example.test", role="mahasiswa")
    login(client, "mhs@example.test")
    assert client.get("/api/support/status").json() == {"staff_online": True}
    assert new_request(client)["kind"] == "livechat"


def test_staf_dianggap_offline_bila_heartbeat_kedaluwarsa(client, make_user, db):
    go_online(client, make_user)
    presence = db.query(StaffPresence).one()
    presence.last_seen_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()
    make_user(email="mhs@example.test", role="mahasiswa")
    login(client, "mhs@example.test")
    assert client.get("/api/support/status").json() == {"staff_online": False}
    assert new_request(client)["kind"] == "tiket"


def test_alur_lengkap_balas_dan_tutup(client, make_user):
    make_user(email="mhs@example.test", role="mahasiswa")
    make_user(email="staf@example.test", role="staf")
    login(client, "mhs@example.test")
    rid = new_request(client)["id"]

    login(client, "staf@example.test")
    queue = client.get("/api/admin/support/requests").json()
    assert [q["id"] for q in queue] == [rid]
    assert queue[0]["student"]["email"] == "mhs@example.test"

    reply = client.post(f"/api/admin/support/requests/{rid}/messages", json={"content": "29 Januari 2027."}).json()
    assert reply["status"] == "aktif"
    assert reply["assigned_staff_name"] == "Pengguna Uji"

    login(client, "mhs@example.test")
    detail = client.get(f"/api/support/requests/{rid}").json()
    assert [m["sender_role"] for m in detail["messages"]] == ["mahasiswa", "staf"]
    assert client.post(f"/api/support/requests/{rid}/messages", json={"content": "Terima kasih"}).status_code == 200

    login(client, "staf@example.test")
    closed = client.post(f"/api/admin/support/requests/{rid}/close").json()
    assert closed["status"] == "selesai" and closed["closed_at"]
    assert client.get("/api/admin/support/requests").json() == []  # default: hanya yang terbuka
    assert [q["id"] for q in client.get("/api/admin/support/requests?status=selesai").json()] == [rid]

    login(client, "mhs@example.test")
    assert client.post(f"/api/support/requests/{rid}/messages", json={"content": "lagi"}).status_code == 409


def test_transkrip_chat_ai_terlampir_untuk_staf(client, make_user, monkeypatch):
    make_user(email="mhs@example.test", role="mahasiswa")
    login(client, "mhs@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1, score=0.5)], ""))
    cid = client.post("/api/chat", json={"question": "Batas yudisium?"}).json()["conversation_id"]
    rid = new_request(client, conversation_id=cid)["id"]

    make_user(email="admin@example.test", role="admin")
    login(client, "admin@example.test")
    detail = client.get(f"/api/admin/support/requests/{rid}").json()
    assert [t["sender"] for t in detail["ai_transcript"]] == ["mahasiswa", "asisten"]
    assert detail["ai_transcript"][1]["escalated"] is True


def test_isolasi_data_antar_mahasiswa(client, make_user, monkeypatch):
    make_user(email="a@example.test", role="mahasiswa")
    make_user(email="b@example.test", role="mahasiswa")
    login(client, "a@example.test")
    monkeypatch.setattr(chat_module.httpx, "post", fake_post([hit(1)], "Jawaban [1]."))
    cid_a = client.post("/api/chat", json={"question": "rahasia A"}).json()["conversation_id"]
    rid = new_request(client)["id"]

    login(client, "b@example.test")
    assert client.get("/api/support/requests").json() == []
    assert client.get(f"/api/support/requests/{rid}").status_code == 404
    assert client.post(f"/api/support/requests/{rid}/messages", json={"content": "x"}).status_code == 404
    # Tidak bisa melampirkan percakapan AI milik mahasiswa lain.
    r = client.post("/api/support/requests", json={"category": "akademik", "message": "halo", "conversation_id": cid_a})
    assert r.status_code == 404


def test_endpoint_admin_tertutup_bagi_mahasiswa(client, make_user):
    make_user(email="mhs@example.test", role="mahasiswa")
    login(client, "mhs@example.test")
    assert client.get("/api/admin/support/requests").status_code == 403
    assert client.put("/api/admin/support/presence", json={"online": True}).status_code == 403


def test_validasi_kategori_dan_pesan(client, make_user):
    make_user(email="mhs@example.test", role="mahasiswa")
    login(client, "mhs@example.test")
    assert client.post("/api/support/requests", json={"category": "asal", "message": "halo"}).status_code == 422
    assert client.post("/api/support/requests", json={"category": "akademik", "message": "   "}).status_code == 422


def test_harus_login(client):
    client.cookies.clear()
    assert client.get("/api/support/status").status_code == 401
    assert client.get("/api/admin/support/requests").status_code == 401
