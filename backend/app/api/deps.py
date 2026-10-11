from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import create_access_token, decode_access_token
from app.models import User


def set_auth_cookie(response: Response, user_id: int) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.cookie_name,
        value=create_access_token(user_id),
        max_age=settings.access_token_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def get_current_user(
    response: Response,
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(default=None, alias=get_settings().cookie_name),
) -> User:
    unauthorized = HTTPException(status.HTTP_401_UNAUTHORIZED, "Belum login atau sesi berakhir.")
    if not access_token:
        raise unauthorized
    user_id = decode_access_token(access_token)
    if user_id is None:
        raise unauthorized
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise unauthorized
    # Sesi bergulir: setiap request terautentikasi memperpanjang masa berlaku,
    # sehingga sesi hanya berakhir setelah tidak aktif selama access_token_minutes.
    set_auth_cookie(response, user.id)
    return user
