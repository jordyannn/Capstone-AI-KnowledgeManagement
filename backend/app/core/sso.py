"""Klien OpenID Connect untuk Microsoft Entra ID (login "Masuk dengan akun Telkom University").

Alur: authorization code + PKCE. Semua validasi id_token dilakukan di sini, karena library OIDC
yang ada tidak melakukannya untuk kita (MSAL >= 1.38 sengaja tidak memvalidasi, dan authlib.jose
sudah deprecated). Yang dipakai hanya PyJWT dan httpx yang memang sudah ada di repo.
"""

import base64
import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from urllib.parse import urlencode

import httpx
import jwt

from app.core.config import Settings, get_settings

log = logging.getLogger("sso")

AUTHORITY = "https://login.microsoftonline.com"
SCOPE = "openid profile email"
# Hanya RS256. Menolak "none" dan HS256 (serangan konfusi: public key dipakai sebagai secret HMAC).
ID_TOKEN_ALGORITHMS = ["RS256"]
STATE_TTL_SECONDS = 600
STATE_AUDIENCE = "kms-sso-state"
# Email @student otomatis jadi Mahasiswa. Domain lain menunggu admin (SCRUM-30).
AUTO_PROVISION_DOMAIN = "student.telkomuniversity.ac.id"


class SsoError(Exception):
    """Kegagalan login SSO. `code` dikirim ke /login?error=<code>; `detail` hanya untuk log server."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SsoIdentity:
    oid: str
    email: str
    name: str


@dataclass(frozen=True)
class SsoState:
    state: str
    nonce: str
    code_verifier: str


# ---- PKCE dan cookie state -------------------------------------------------------------------


def new_random() -> str:
    return secrets.token_urlsafe(32)


def new_code_verifier() -> str:
    return secrets.token_urlsafe(64)  # 86 karakter; RFC 7636 mengizinkan 43-128


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def encode_state(sso_state: SsoState, settings: Settings | None = None) -> str:
    """Cookie `sso_state`: JWT bertanda tangan (terjaga integritasnya, tetapi terbaca browser).

    `aud` khusus memastikan token sesi login tidak bisa dipakai sebagai state, dan sebaliknya
    (decode_access_token menolak token ber-`aud`)."""
    settings = settings or get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "aud": STATE_AUDIENCE,
        "iat": now,
        "exp": now + timedelta(seconds=STATE_TTL_SECONDS),
        "state": sso_state.state,
        "nonce": sso_state.nonce,
        "cv": sso_state.code_verifier,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_state(token: str | None, settings: Settings | None = None) -> SsoState:
    settings = settings or get_settings()
    if not token:
        raise SsoError("sesi_kedaluwarsa", "cookie sso_state tidak ada")
    try:
        data = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm],
            audience=STATE_AUDIENCE,
            options={"require": ["exp", "aud"]},
        )
        return SsoState(state=data["state"], nonce=data["nonce"], code_verifier=data["cv"])
    except (jwt.PyJWTError, KeyError) as error:
        raise SsoError("sesi_kedaluwarsa", f"cookie sso_state tidak valid: {type(error).__name__}") from error


def states_match(received: str | None, saved: str) -> bool:
    return bool(received) and hmac.compare_digest(received, saved)


# ---- Validasi identitas ----------------------------------------------------------------------


def email_domain(email: str) -> str:
    return email.rsplit("@", 1)[-1] if "@" in email else ""


def email_domain_allowed(email: str, allowed: set[str]) -> bool:
    """Cocok persis dengan domain, bukan akhiran: "student.x.ac.id.evil.com" harus ditolak."""
    return email_domain(email.strip().lower()) in allowed


# ---- Klien OIDC ------------------------------------------------------------------------------


class MicrosoftOidc:
    def __init__(self, settings: Settings):
        self.settings = settings
        base = f"{AUTHORITY}/{settings.sso_tenant_id}"
        self.authorize_endpoint = f"{base}/oauth2/v2.0/authorize"
        self.token_endpoint = f"{base}/oauth2/v2.0/token"
        self.jwks_uri = f"{base}/discovery/v2.0/keys"
        self.issuer = f"{base}/v2.0"
        self._jwks: jwt.PyJWKClient | None = None

    def authorization_url(self, state: str, nonce: str, challenge: str) -> str:
        params = {
            "client_id": self.settings.sso_client_id,
            "response_type": "code",
            "redirect_uri": self.settings.sso_redirect_uri,
            "response_mode": "query",
            "scope": SCOPE,
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            # Komputer lab dipakai bergantian: biarkan pengguna memilih akun, bukan langsung masuk
            # sebagai akun Microsoft yang kebetulan masih aktif di browser.
            "prompt": "select_account",
        }
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    def exchange_code(self, code: str, code_verifier: str) -> str:
        """Tukar authorization code dengan id_token. Mengembalikan id_token mentah."""
        data = {
            "client_id": self.settings.sso_client_id,
            "client_secret": self.settings.sso_client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.settings.sso_redirect_uri,
            "code_verifier": code_verifier,
        }
        try:
            response = httpx.post(self.token_endpoint, data=data, timeout=10.0)
        except httpx.HTTPError as error:
            raise SsoError("gagal", f"token endpoint tidak terjangkau: {type(error).__name__}") from error
        if response.status_code != 200:
            try:
                reason = response.json().get("error", "?")
            except ValueError:
                reason = "?"
            # Hanya kode error; badan respons bisa memuat detail yang tidak perlu masuk log.
            raise SsoError("gagal", f"token endpoint HTTP {response.status_code} error={reason}")
        id_token = response.json().get("id_token")
        if not id_token:
            raise SsoError("gagal", "respons token tanpa id_token")
        return id_token

    def _signing_key(self, id_token: str):
        """Kunci publik penanda tangan id_token dari JWKS Microsoft (di-cache PyJWKClient; kunci
        baru diambil otomatis saat `kid` belum dikenal). Dipisah supaya test bisa menggantinya."""
        if self._jwks is None:
            self._jwks = jwt.PyJWKClient(self.jwks_uri, cache_keys=True, lifespan=3600, timeout=10)
        return self._jwks.get_signing_key_from_jwt(id_token).key

    def validate_id_token(self, id_token: str, nonce: str) -> SsoIdentity:
        settings = self.settings
        try:
            claims = jwt.decode(
                id_token,
                self._signing_key(id_token),
                algorithms=ID_TOKEN_ALGORITHMS,
                audience=settings.sso_client_id,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                leeway=60,
            )
        except jwt.PyJWTError as error:
            raise SsoError("gagal", f"id_token tidak valid: {type(error).__name__}: {error}") from error

        if not hmac.compare_digest(str(claims.get("nonce", "")), nonce):
            raise SsoError("gagal", "nonce tidak cocok")
        if claims.get("tid") != settings.sso_tenant_id:
            raise SsoError("akun_tidak_diizinkan", f"tid {claims.get('tid')!r} bukan tenant yang diizinkan")
        oid = str(claims.get("oid") or "").strip()
        if not oid:
            raise SsoError("gagal", "klaim oid tidak ada")

        email = str(claims.get("email") or claims.get("preferred_username") or "").strip().lower()
        if "@" not in email:
            raise SsoError("akun_tidak_diizinkan", f"oid={oid}: tidak ada email/preferred_username")
        if not email_domain_allowed(email, settings.sso_domains):
            raise SsoError("akun_tidak_diizinkan", f"oid={oid}: domain {email_domain(email)!r} tidak diizinkan")

        name = str(claims.get("name") or "").strip() or email.split("@")[0]
        return SsoIdentity(oid=oid, email=email, name=name[:255])


@lru_cache
def _default_oidc() -> MicrosoftOidc:
    return MicrosoftOidc(get_settings())


def get_oidc() -> MicrosoftOidc:
    """Dependency FastAPI. Test menggantinya dengan klien palsu."""
    return _default_oidc()
