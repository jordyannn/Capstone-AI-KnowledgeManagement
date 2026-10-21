"""Endpoint login SSO Microsoft. Sesi, logout, dan /me tetap milik login lokal (auth.py/deps.py)."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import set_auth_cookie
from app.core.config import get_settings
from app.core.db import get_db
from app.core.sso import (
    AUTO_PROVISION_DOMAIN,
    MicrosoftOidc,
    SsoError,
    SsoIdentity,
    SsoState,
    code_challenge,
    decode_state,
    email_domain,
    encode_state,
    get_oidc,
    new_code_verifier,
    new_random,
    states_match,
)
from app.models import Role, User
from app.models.user import AUTH_MICROSOFT

log = logging.getLogger("sso")

router = APIRouter(prefix="/auth/sso", tags=["sso"])

STATE_COOKIE = "sso_state"
STATE_COOKIE_PATH = "/api/auth/sso"
STATE_MAX_AGE = 600


def _require_enabled() -> None:
    if not get_settings().sso_enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND)


def _clear_state_cookie(response: RedirectResponse) -> None:
    response.delete_cookie(STATE_COOKIE, path=STATE_COOKIE_PATH)


def _failure(error: SsoError) -> RedirectResponse:
    # Pengguna hanya melihat kode singkat; detailnya (tanpa token) hanya di log server.
    log.warning("SSO gagal [%s] %s", error.code, error.detail)
    response = RedirectResponse(f"/login?error={error.code}", status_code=status.HTTP_302_FOUND)
    _clear_state_cookie(response)
    return response


@router.get("/status")
def sso_status() -> dict[str, bool]:
    """Selalu 200, supaya halaman login tahu perlu menampilkan tombol SSO atau tidak."""
    return {"enabled": get_settings().sso_enabled}


@router.get("/login")
def sso_login(oidc: MicrosoftOidc = Depends(get_oidc)) -> RedirectResponse:
    _require_enabled()
    settings = get_settings()
    sso_state = SsoState(state=new_random(), nonce=new_random(), code_verifier=new_code_verifier())
    url = oidc.authorization_url(sso_state.state, sso_state.nonce, code_challenge(sso_state.code_verifier))
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key=STATE_COOKIE,
        value=encode_state(sso_state, settings),
        max_age=STATE_MAX_AGE,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",  # callback adalah navigasi top-level dari Microsoft; "strict" akan memblokirnya
        path=STATE_COOKIE_PATH,
    )
    return response


def _find_by_external_id(db: Session, oid: str) -> User | None:
    return db.scalar(select(User).where(User.external_id == oid))


def _resolve_user(db: Session, identity: SsoIdentity) -> User:
    user = _find_by_external_id(db, identity.oid)

    if user is None:
        user = db.scalar(select(User).where(User.email == identity.email))
        if user is not None:
            # Akun sudah disiapkan (mis. oleh admin, lengkap dengan perannya): tautkan ke identitas
            # Microsoft ini. Akun yang sudah tertaut ke orang lain tidak boleh dibajak lewat email.
            if user.external_id and user.external_id != identity.oid:
                raise SsoError("akun_tidak_diizinkan", f"{identity.email} sudah tertaut ke identitas Microsoft lain")
            if not user.is_active:
                raise SsoError("akun_nonaktif", f"{identity.email} dinonaktifkan")
            user.external_id = identity.oid
        else:
            if email_domain(identity.email) != AUTO_PROVISION_DOMAIN:
                raise SsoError("belum_terdaftar", f"{identity.email} belum terdaftar; peran diberikan admin")
            role = db.scalar(select(Role).where(Role.code == "mahasiswa"))
            if role is None:
                raise SsoError("gagal", "peran 'mahasiswa' belum ada di tabel roles")
            user = User(
                email=identity.email,
                full_name=identity.name,
                password_hash=None,
                role_id=role.id,
                auth_provider=AUTH_MICROSOFT,
                external_id=identity.oid,
                # Eksplisit: default kolom baru terisi saat INSERT, sedangkan pengecekan
                # is_active di bawah berjalan sebelum itu (nilainya masih None).
                is_active=True,
            )
            db.add(user)

    if not user.is_active:
        raise SsoError("akun_nonaktif", f"oid={identity.oid} dinonaktifkan")
    return user


def _resolve_and_commit(db: Session, identity: SsoIdentity) -> User:
    try:
        user = _resolve_user(db, identity)
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        return user
    except IntegrityError:
        # Dua callback bersamaan untuk pengguna baru yang sama: yang kalah mengambil baris pemenang.
        db.rollback()
        user = _find_by_external_id(db, identity.oid)
        if user is None:
            raise SsoError("gagal", "konflik data saat membuat user") from None
        if not user.is_active:
            raise SsoError("akun_nonaktif", f"oid={identity.oid} dinonaktifkan") from None
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        return user


@router.get("/callback")
def sso_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
    oidc: MicrosoftOidc = Depends(get_oidc),
) -> RedirectResponse:
    _require_enabled()
    try:
        if error:
            # Microsoft mengembalikan error (mis. pengguna menekan "Batal"). error_description tidak dipakai.
            raise SsoError("dibatalkan" if error == "access_denied" else "gagal", f"Microsoft mengembalikan error={error}")

        saved = decode_state(request.cookies.get(STATE_COOKIE))
        if not states_match(state, saved.state):
            raise SsoError("sesi_kedaluwarsa", "parameter state tidak cocok dengan cookie")
        if not code:
            raise SsoError("gagal", "parameter code tidak ada")

        id_token = oidc.exchange_code(code, saved.code_verifier)
        identity = oidc.validate_id_token(id_token, saved.nonce)
        user = _resolve_and_commit(db, identity)
    except SsoError as failure:
        return _failure(failure)

    response = RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    set_auth_cookie(response, user.id)  # cookie sesi yang sama dengan login lokal
    _clear_state_cookie(response)
    return response
