"""Seed data awal. Idempoten: aman dijalankan setiap container start.

    python -m app.seed
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Role, User

ROLES = [
    ("admin", "Admin"),
    ("kaprodi", "Kaprodi"),
    ("dosen", "Dosen"),
    ("staf", "Staf Administrasi"),
    ("mahasiswa", "Mahasiswa"),
]


def seed_roles(db: Session) -> None:
    existing = set(db.scalars(select(Role.code)))
    for code, name in ROLES:
        if code not in existing:
            db.add(Role(code=code, name=name))
    db.commit()


def seed_admin(db: Session) -> bool:
    settings = get_settings()
    if not (settings.seed_admin_email and settings.seed_admin_password):
        return False
    email = settings.seed_admin_email.strip().lower()
    if db.scalar(select(User).where(User.email == email)):
        return False
    admin_role = db.scalar(select(Role).where(Role.code == "admin"))
    db.add(
        User(
            email=email,
            full_name=settings.seed_admin_name,
            password_hash=hash_password(settings.seed_admin_password),
            role_id=admin_role.id,
        )
    )
    db.commit()
    return True


def main() -> None:
    with SessionLocal() as db:
        seed_roles(db)
        created = seed_admin(db)
    print("seed: roles ok;", "admin dibuat" if created else "admin tidak diubah")


if __name__ == "__main__":
    main()
