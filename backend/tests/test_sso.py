"""Test login SSO Microsoft. Tidak ada panggilan ke Microsoft: penukaran code diganti, dan kunci
publik JWKS diganti kunci RSA buatan test. Validasi id_token sendiri (signature, iss, aud, exp,
nonce, tid, domain) berjalan sungguhan."""

import base64
import hashlib
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.config import Settings, get_settings
from app.core.security import create_access_token
from app.core.sso import MicrosoftOidc, SsoError, email_domain_allowed, get_oidc
from app.main import app
from app.models import Role, User
from tests.conftest import PASSWORD

S = get_settings()
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISSUER = f"https://login.microsoftonline.com/{S.sso_tenant_id}/v2.0"
STUDENT = "mhs@student.telkomuniversity.ac.id"


class FakeOidc(MicrosoftOidc):
    """Klien asli, kecuali penukaran code dan pengambilan kunci publik."""

    def __init__(self, settings):
        super().__init__(settings)
        self.id_token = None
        self.exchange_error = None
        self.calls = []

    def exchange_code(self, code, code_verifier):
        self.calls.append((code, code_verifier))
        if self.exchange_error:
            raise self.exchange_error
        return self.id_token

    def _signing_key(self, id_token):
        return KEY.public_key()


@pytest.fixture()
def oidc(client):
    fake = FakeOidc(get_settings())
    app.dependency_overrides[get_oidc] = lambda: fake
    return fake


def claims(**overrides):
    now = int(time.time())
    base = {
        "iss": ISSUER,
        "aud": S.sso_client_id,
        "iat": now,
        "nbf": now,
        "exp": now + 3600,
        "sub": "sub-abc",
        "oid": "oid-111",
        "tid": S.sso_tenant_id,
        "email": STUDENT,
        "preferred_username": STUDENT,
        "name": "Mahasiswa Uji",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}  # None = klaim dihilangkan


def sign(payload, key=KEY, algorithm="RS256"):
    return jwt.encode(payload, key, algorithm=algorithm, headers={"kid": "test-kid"})


def begin(client):
    response = client.get("/api/auth/sso/login", follow_redirects=False)
    assert response.status_code == 302
    return response, {k: v[0] for k, v in parse_qs(urlparse(response.headers["location"]).query).items()}


def finish(client, oidc, params, *, key=KEY, algorithm="RS256", state=None, code="kode-otorisasi", **claim_overrides):
    claim_overrides.setdefault("nonce", params["nonce"])
    oidc.id_token = sign(claims(**claim_overrides), key=key, algorithm=algorithm)
    return client.get(
        "/api/auth/sso/callback", params={"code": code, "state": state or params["state"]}, follow_redirects=False
    )


def sso_login(client, oidc, **kwargs):
    _, params = begin(client)
    return finish(client, oidc, params, **kwargs)


def assert_failed(response, code):
    assert response.status_code == 302
    assert response.headers["location"] == f"/login?error={code}"  # hanya kode, tanpa detail
    assert "access_token" not in "".join(response.headers.get_list("set-cookie"))


def users(db):
    db.expire_all()
    return db.scalars(select(User)).all()


# ---- status, login, dan konfigurasi -------------------------------------------------------------


def test_status_reports_enabled(client):
    assert client.get("/api/auth/sso/status").json() == {"enabled": True}


def test_status_reports_disabled_but_endpoints_return_404(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "sso_enabled", False)
    assert client.get("/api/auth/sso/status").json() == {"enabled": False}
    assert client.get("/api/auth/sso/login", follow_redirects=False).status_code == 404
    assert client.get("/api/auth/sso/callback?code=x&state=y", follow_redirects=False).status_code == 404


def test_enabled_without_credentials_fails_at_startup():
    with pytest.raises(ValidationError, match="SSO_CLIENT_ID"):
        Settings(secret_key="x" * 32, sso_enabled=True, sso_client_id="", sso_client_secret="")
    Settings(secret_key="x" * 32, sso_enabled=False)  # mati: tidak butuh kredensial


def test_login_redirects_to_tenant_authorize_endpoint_with_pkce(client, oidc):
    response, params = begin(client)
    url = urlparse(response.headers["location"])
    assert (url.scheme, url.netloc) == ("https", "login.microsoftonline.com")
    assert url.path == f"/{S.sso_tenant_id}/oauth2/v2.0/authorize"
    assert params["client_id"] == S.sso_client_id
    assert params["redirect_uri"] == S.sso_redirect_uri
    assert params["response_type"] == "code"
    assert params["scope"] == "openid profile email"
    assert params["code_challenge_method"] == "S256"
    assert params["prompt"] == "select_account"
    assert len(params["state"]) >= 32 and len(params["nonce"]) >= 32 and params["state"] != params["nonce"]


def test_login_sets_short_lived_httponly_state_cookie_scoped_to_sso_path(client, oidc):
    response, _ = begin(client)
    cookie = next(c for c in response.headers.get_list("set-cookie") if c.startswith("sso_state="))
    lowered = cookie.lower()
    assert "httponly" in lowered and "samesite=lax" in lowered
    assert "path=/api/auth/sso" in lowered and "max-age=600" in lowered


def test_each_login_attempt_gets_fresh_state_nonce_and_verifier(client, oidc):
    _, first = begin(client)
    _, second = begin(client)
    assert first["state"] != second["state"]
    assert first["nonce"] != second["nonce"]
    assert first["code_challenge"] != second["code_challenge"]


def test_domain_matching_is_exact_not_suffix():
    allowed = S.sso_domains
    assert email_domain_allowed("a@student.telkomuniversity.ac.id", allowed)
    assert email_domain_allowed("A@Telkomuniversity.AC.ID", allowed)
    assert not email_domain_allowed("a@student.telkomuniversity.ac.id.evil.com", allowed)
    assert not email_domain_allowed("a@evilstudent.telkomuniversity.ac.id", allowed)
    assert not email_domain_allowed("a@gmail.com", allowed)
    assert not email_domain_allowed("tanpa-at", allowed)


# ---- jalur sukses ------------------------------------------------------------------------------------


def test_new_student_is_created_as_mahasiswa_and_gets_a_session(client, oidc, db):
    response = sso_login(client, oidc)

    assert response.status_code == 302 and response.headers["location"] == "/"
    [user] = users(db)
    assert user.email == STUDENT and user.full_name == "Mahasiswa Uji"
    assert user.role.code == "mahasiswa"
    assert user.auth_provider == "microsoft" and user.external_id == "oid-111"
    assert user.password_hash is None
    assert user.last_login_at is not None

    cookies = response.headers.get_list("set-cookie")
    session = next(c for c in cookies if c.startswith("access_token=")).lower()
    assert "httponly" in session and "samesite=lax" in session
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == STUDENT and me.json()["role"]["code"] == "mahasiswa"


def test_email_is_normalised_to_lowercase(client, oidc, db):
    sso_login(client, oidc, email="Mhs@Student.TelkomUniversity.ac.id", preferred_username=None)
    assert users(db)[0].email == STUDENT


def test_falls_back_to_preferred_username_when_email_claim_is_missing(client, oidc, db):
    response = sso_login(client, oidc, email=None)
    assert response.headers["location"] == "/"
    assert users(db)[0].email == STUDENT


def test_pkce_verifier_sent_to_token_endpoint_matches_the_challenge(client, oidc):
    _, params = begin(client)
    finish(client, oidc, params, code="abc123")
    [(code, verifier)] = oidc.calls
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert code == "abc123" and expected == params["code_challenge"]


def test_state_cookie_is_single_use(client, oidc):
    _, params = begin(client)
    assert finish(client, oidc, params).headers["location"] == "/"
    assert_failed(finish(client, oidc, params), "sesi_kedaluwarsa")  # cookie sudah dihapus


def test_existing_sso_user_is_found_by_oid_even_if_email_changed(client, oidc, db, make_user):
    make_user(email=STUDENT, role="mahasiswa", password=None, external_id="oid-111")
    response = sso_login(client, oidc, email="nama-baru@student.telkomuniversity.ac.id", preferred_username=None)
    assert response.headers["location"] == "/"
    [user] = users(db)
    assert user.email == STUDENT  # tidak diubah diam-diam


def test_preregistered_account_is_linked_by_email_and_keeps_its_role(client, oidc, db, make_user):
    make_user(email="dosen@telkomuniversity.ac.id", role="dosen")
    response = sso_login(
        client, oidc, oid="oid-dosen", email="dosen@telkomuniversity.ac.id", preferred_username=None
    )

    assert response.headers["location"] == "/"
    [user] = users(db)
    assert user.external_id == "oid-dosen" and user.role.code == "dosen"
    assert len(users(db)) == 1  # tidak membuat akun ganda
    assert client.get("/api/auth/me").json()["role"]["code"] == "dosen"
    # Sandi lokal tetap berfungsi setelah ditautkan.
    login = client.post("/api/auth/login", json={"email": "dosen@telkomuniversity.ac.id", "password": PASSWORD})
    assert login.status_code == 200


# ---- penolakan ------------------------------------------------------------------------------------------


def test_unregistered_non_student_is_not_created_automatically(client, oidc, db):
    response = sso_login(client, oidc, email="dosen@telkomuniversity.ac.id", preferred_username=None)
    assert_failed(response, "belum_terdaftar")
    assert users(db) == []


@pytest.mark.parametrize(
    "email",
    [
        "orang@gmail.com",
        "mhs@student.telkomuniversity.ac.id.evil.com",
        "mhs@evilstudent.telkomuniversity.ac.id",
    ],
)
def test_domain_not_allowed_is_rejected(client, oidc, db, email):
    assert_failed(sso_login(client, oidc, email=email, preferred_username=email), "akun_tidak_diizinkan")
    assert users(db) == []


def test_missing_email_and_preferred_username_is_rejected(client, oidc, db):
    assert_failed(sso_login(client, oidc, email=None, preferred_username=None), "akun_tidak_diizinkan")
    assert users(db) == []


def test_token_from_another_tenant_is_rejected(client, oidc, db):
    response = sso_login(client, oidc, tid="11111111-2222-3333-4444-555555555555")
    assert_failed(response, "akun_tidak_diizinkan")
    assert users(db) == []


def test_link_refused_when_account_already_belongs_to_another_microsoft_identity(client, oidc, db, make_user):
    make_user(email=STUDENT, role="mahasiswa", password=None, external_id="oid-milik-orang-lain")
    assert_failed(sso_login(client, oidc, oid="oid-penyerang"), "akun_tidak_diizinkan")
    assert users(db)[0].external_id == "oid-milik-orang-lain"  # tidak dibajak


def test_inactive_user_matched_by_oid_is_rejected(client, oidc, make_user):
    make_user(email=STUDENT, role="mahasiswa", password=None, external_id="oid-111", active=False)
    assert_failed(sso_login(client, oidc), "akun_nonaktif")


def test_inactive_user_matched_by_email_is_rejected_and_not_linked(client, oidc, db, make_user):
    make_user(email=STUDENT, role="mahasiswa", active=False)
    assert_failed(sso_login(client, oidc), "akun_nonaktif")
    assert users(db)[0].external_id is None


def test_missing_mahasiswa_role_fails_cleanly(client, oidc, db):
    db.query(Role).filter_by(code="mahasiswa").delete()
    db.commit()
    assert_failed(sso_login(client, oidc), "gagal")
    assert users(db) == []


# ---- validasi state ------------------------------------------------------------------------------------------


def test_wrong_state_parameter_is_rejected(client, oidc, db):
    _, params = begin(client)
    assert_failed(finish(client, oidc, params, state="state-palsu"), "sesi_kedaluwarsa")
    assert users(db) == []


def test_missing_state_cookie_is_rejected(client, oidc):
    _, params = begin(client)
    client.cookies.clear()
    assert_failed(finish(client, oidc, params), "sesi_kedaluwarsa")


def test_tampered_state_cookie_is_rejected(client, oidc):
    _, params = begin(client)
    client.cookies.set("sso_state", "bukan.jwt.valid", path="/api/auth/sso")
    assert_failed(finish(client, oidc, params), "sesi_kedaluwarsa")


def test_expired_state_cookie_is_rejected(client, oidc):
    _, params = begin(client)
    past = datetime.now(timezone.utc) - timedelta(minutes=30)
    stale = jwt.encode(
        {"aud": "kms-sso-state", "iat": past, "exp": past + timedelta(minutes=10),
         "state": params["state"], "nonce": params["nonce"], "cv": "verifier"},
        S.secret_key, algorithm=S.jwt_algorithm,
    )
    client.cookies.set("sso_state", stale, path="/api/auth/sso")
    assert_failed(finish(client, oidc, params), "sesi_kedaluwarsa")


def test_session_token_cannot_be_used_as_state_cookie(client, oidc):
    _, params = begin(client)
    client.cookies.set("sso_state", create_access_token(1), path="/api/auth/sso")
    assert_failed(finish(client, oidc, params), "sesi_kedaluwarsa")


def test_state_cookie_cannot_be_used_as_session(client, oidc):
    response, _ = begin(client)
    state_cookie = client.cookies.get("sso_state", path="/api/auth/sso")
    assert state_cookie
    client.cookies.set("access_token", state_cookie)
    assert client.get("/api/auth/me").status_code == 401


# ---- validasi id_token -----------------------------------------------------------------------------------------


def test_wrong_nonce_is_rejected(client, oidc, db):
    assert_failed(sso_login(client, oidc, nonce="nonce-lain"), "gagal")
    assert users(db) == []


def test_wrong_audience_is_rejected(client, oidc):
    assert_failed(sso_login(client, oidc, aud="aplikasi-lain"), "gagal")


def test_wrong_issuer_is_rejected(client, oidc):
    other = "https://login.microsoftonline.com/11111111-2222-3333-4444-555555555555/v2.0"
    assert_failed(sso_login(client, oidc, iss=other), "gagal")


def test_expired_id_token_is_rejected(client, oidc):
    assert_failed(sso_login(client, oidc, exp=int(time.time()) - 3600), "gagal")


def test_id_token_without_required_claims_is_rejected(client, oidc):
    assert_failed(sso_login(client, oidc, iat=None), "gagal")
    assert_failed(sso_login(client, oidc, oid=None), "gagal")


def test_id_token_signed_with_another_key_is_rejected(client, oidc, db):
    assert_failed(sso_login(client, oidc, key=OTHER_KEY), "gagal")
    assert users(db) == []


def test_id_token_with_hmac_algorithm_is_rejected(client, oidc, db):
    _, params = begin(client)
    # Serangan konfusi algoritma: token ditandatangani HS256 alih-alih RS256.
    assert_failed(finish(client, oidc, params, key=b"k" * 32, algorithm="HS256"), "gagal")
    assert users(db) == []


def test_unsigned_id_token_is_rejected(client, oidc, db):
    _, params = begin(client)
    assert_failed(finish(client, oidc, params, key=None, algorithm="none"), "gagal")
    assert users(db) == []


# ---- error dari Microsoft dan token endpoint ----------------------------------------------------------------------


def test_user_cancelling_at_microsoft_is_reported_as_cancelled(client, oidc):
    response = client.get("/api/auth/sso/callback?error=access_denied&error_description=rahasia", follow_redirects=False)
    assert_failed(response, "dibatalkan")
    assert "rahasia" not in response.headers["location"]


def test_other_microsoft_errors_are_generic(client, oidc):
    response = client.get("/api/auth/sso/callback?error=server_error", follow_redirects=False)
    assert_failed(response, "gagal")


def test_token_endpoint_failure_is_generic_and_leaks_nothing(client, oidc, db):
    _, params = begin(client)
    oidc.exchange_error = SsoError("gagal", "token endpoint HTTP 400 error=invalid_grant")
    response = client.get("/api/auth/sso/callback", params={"code": "x", "state": params["state"]}, follow_redirects=False)
    assert_failed(response, "gagal")
    assert "invalid_grant" not in response.headers["location"]
    assert users(db) == []


def test_missing_code_is_rejected(client, oidc):
    _, params = begin(client)
    response = client.get("/api/auth/sso/callback", params={"state": params["state"]}, follow_redirects=False)
    assert_failed(response, "gagal")


def test_concurrent_first_login_falls_back_to_the_winning_row(client, oidc, db, make_user, monkeypatch):
    make_user(email=STUDENT, role="mahasiswa", password=None, external_id="oid-111")

    def lost_race(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr("app.api.sso._resolve_user", lost_race)
    assert sso_login(client, oidc).headers["location"] == "/"


def test_integrity_error_without_a_winning_row_fails_cleanly(client, oidc, monkeypatch):
    def broken(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("duplicate"))

    monkeypatch.setattr("app.api.sso._resolve_user", broken)
    assert_failed(sso_login(client, oidc), "gagal")


# ---- login lokal tidak boleh terpengaruh ------------------------------------------------------------------------------


def test_sso_user_cannot_log_in_with_a_password(client, oidc, make_user):
    make_user(email=STUDENT, role="mahasiswa", password=None, external_id="oid-111")
    generic = client.post("/api/auth/login", json={"email": STUDENT, "password": "salah"})
    assert generic.status_code == 401

    for guess in ("x", PASSWORD, "dummy-password"):  # "dummy-password" cocok dengan DUMMY_HASH
        response = client.post("/api/auth/login", json={"email": STUDENT, "password": guess})
        assert response.status_code == 401
        assert response.json() == generic.json()  # pesan sama dengan sandi salah biasa
