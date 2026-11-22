from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, set_auth_cookie
from app.core import audit
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import DUMMY_HASH, verify_password
from app.models import User
from app.models.audit import LOGIN, LOGIN_FAILED
from app.models.support import STAFF_ROLES
from app.schemas.auth import LoginRequest, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)) -> User:
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email))

    # Selalu verifikasi hash agar waktu respons tidak membocorkan apakah email terdaftar.
    # User SSO tidak punya password_hash: tetap verifikasi hash tiruan (waktu sama), lalu tolak
    # secara eksplisit. Penolakan tidak boleh bergantung pada hasil verifikasi, karena hash tiruan
    # cocok dengan sandi "dummy-password".
    has_password = user is not None and user.password_hash is not None
    password_ok = verify_password(payload.password, user.password_hash if has_password else DUMMY_HASH)
    if user is None or not has_password or not password_ok or not user.is_active:
        # F-15: upaya login gagal dicatat (email yang dicoba, tanpa sandi) untuk mendeteksi tebak-sandi.
        audit.record(db, LOGIN_FAILED, actor_email=email[:255], detail={"metode": "sandi"})
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email atau kata sandi salah.")

    user.last_login_at = datetime.now(timezone.utc)
    if user.role.code in STAFF_ROLES:  # login mahasiswa tidak dicatat (bukan aktivitas admin)
        audit.record(db, LOGIN, user, detail={"metode": "sandi"})
    db.commit()
    set_auth_cookie(response, user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(key=settings.cookie_name, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user
