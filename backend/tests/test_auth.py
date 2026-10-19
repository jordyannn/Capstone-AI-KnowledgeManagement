import jwt
from fastapi.testclient import TestClient

from app.core.config import get_settings
from tests.conftest import PASSWORD


def login(client: TestClient, email="dosen@example.test", password=PASSWORD):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_success_sets_httponly_cookie_and_returns_role(client, make_user):
    make_user(role="kaprodi")
    r = login(client)
    assert r.status_code == 200
    assert r.json()["role"] == {"code": "kaprodi", "name": "Kaprodi"}
    assert "password" not in r.text
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_login_email_is_case_insensitive(client, make_user):
    make_user(email="dosen@example.test")
    assert login(client, email="  DOSEN@Example.Test ").status_code == 200


def test_login_wrong_password_and_unknown_email_look_identical(client, make_user):
    make_user()
    wrong = login(client, password="salah")
    unknown = login(client, email="tidak-ada@example.test")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_login_inactive_user_rejected(client, make_user):
    make_user(active=False)
    assert login(client).status_code == 401


def test_login_overlong_password_rejected_not_truncated(client, make_user):
    make_user()
    assert login(client, password=PASSWORD + "x" * 100).status_code == 401


def test_me_requires_login(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_after_login(client, make_user):
    make_user()
    login(client)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == "dosen@example.test"


def test_logout_ends_session(client, make_user):
    make_user()
    login(client)
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_tampered_token_rejected(client, make_user):
    make_user()
    login(client)
    client.cookies.set(get_settings().cookie_name, "bukan.token.valid")
    assert client.get("/api/auth/me").status_code == 401


def test_token_signed_with_other_key_rejected(client, make_user):
    user = make_user()
    forged = jwt.encode({"sub": str(user.id)}, "kunci-lain-kunci-lain-kunci-lain-0000", algorithm="HS256")
    client.cookies.set(get_settings().cookie_name, forged)
    assert client.get("/api/auth/me").status_code == 401


def test_deactivated_user_loses_access_with_existing_token(client, make_user, db):
    user = make_user()
    login(client)
    user.is_active = False
    db.commit()
    assert client.get("/api/auth/me").status_code == 401


def test_authenticated_request_refreshes_cookie(client, make_user):
    make_user()
    login(client)
    r = client.get("/api/auth/me")
    assert get_settings().cookie_name in r.headers["set-cookie"]
