"""Log audit (F-15): aksi admin/staf dan login gagal tercatat; hanya staf yang bisa membaca."""

from app.models import AuditLog
from tests.conftest import PASSWORD
from tests.test_support import login, new_request


def actions(db):
    return [(a.action, a.actor_email) for a in db.query(AuditLog).order_by(AuditLog.id)]


def test_login_staf_dicatat_login_mahasiswa_tidak(client, make_user, db):
    make_user(email="staf@example.test", role="staf")
    make_user(email="mhs@example.test", role="mahasiswa")
    login(client, "staf@example.test")
    login(client, "mhs@example.test")
    assert actions(db) == [("login", "staf@example.test")]


def test_login_gagal_dicatat_tanpa_sandi(client, make_user, db):
    make_user(email="mhs@example.test", role="mahasiswa")
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "MHS@example.test", "password": "salah-sandi"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "tidakada@example.test", "password": "x"}).status_code == 401
    log = db.query(AuditLog).order_by(AuditLog.id).all()
    assert [(a.action, a.actor_email) for a in log] == [("login_gagal", "mhs@example.test"), ("login_gagal", "tidakada@example.test")]
    assert all("salah-sandi" not in str(a.detail) for a in log)


def test_balas_tutup_dan_status_online_dicatat(client, make_user, db):
    make_user(email="mhs@example.test", role="mahasiswa")
    make_user(email="staf@example.test", role="staf")
    login(client, "mhs@example.test")
    rid = new_request(client)["id"]

    login(client, "staf@example.test")
    client.put("/api/admin/support/presence", json={"online": True})
    client.put("/api/admin/support/presence", json={"online": True})  # klik ulang: tidak dicatat dua kali
    client.post(f"/api/admin/support/requests/{rid}/messages", json={"content": "NIM saya rahasia"})
    client.post(f"/api/admin/support/requests/{rid}/close")
    client.post(f"/api/admin/support/requests/{rid}/close")  # sudah tertutup: tidak dicatat lagi
    client.put("/api/admin/support/presence", json={"online": False})

    log = [a for a in db.query(AuditLog).order_by(AuditLog.id) if a.action != "login"]
    assert [a.action for a in log] == ["status_online", "bantuan_balas", "bantuan_tutup", "status_offline"]
    assert log[1].target_id == rid and log[2].target_type == "support_request"
    # Isi pesan tidak ikut tersimpan di log.
    assert all("rahasia" not in str(a.detail) for a in log)


def test_endpoint_audit_hanya_untuk_staf_dan_bisa_disaring(client, make_user):
    make_user(email="mhs@example.test", role="mahasiswa")
    make_user(email="admin@example.test", role="admin")
    login(client, "mhs@example.test")
    assert client.get("/api/admin/audit").status_code == 403

    login(client, "admin@example.test")
    client.put("/api/admin/support/presence", json={"online": True})
    entries = client.get("/api/admin/audit").json()
    assert [e["action"] for e in entries] == ["status_online", "login"]  # terbaru di atas
    assert entries[0]["actor_name"] == "Pengguna Uji"
    only = client.get("/api/admin/audit?action=login").json()
    assert [e["action"] for e in only] == ["login"]
    older = client.get(f"/api/admin/audit?before={entries[0]['id']}").json()
    assert [e["action"] for e in older] == ["login"]


def test_sandi_tidak_pernah_tersimpan_di_log(client, make_user, db):
    make_user(email="staf@example.test", role="staf")
    client.cookies.clear()
    assert client.post("/api/auth/login", json={"email": "staf@example.test", "password": PASSWORD}).status_code == 200
    assert PASSWORD not in str([a.detail for a in db.query(AuditLog)])
