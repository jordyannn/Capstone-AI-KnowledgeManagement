from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Role(Base):
    """Peran disimpan sebagai data, bukan hard-coded, agar matriks RBAC (SCRUM-25) bisa berubah."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))


AUTH_LOCAL = "local"
AUTH_MICROSOFT = "microsoft"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    # Kosong untuk user yang dibuat lewat SSO: mereka tidak bisa login dengan sandi.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Asal akun ("local" / "microsoft"). Menentukan cara akun dibuat, bukan cara login yang boleh:
    # login sandi diizinkan hanya bila password_hash terisi.
    auth_provider: Mapped[str] = mapped_column(String(16), default=AUTH_LOCAL, server_default=AUTH_LOCAL)
    # Klaim "oid" Entra ID (stabil per pengguna di satu tenant). Kunci identitas SSO, bukan email.
    external_id: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    role: Mapped[Role] = relationship(lazy="joined")
