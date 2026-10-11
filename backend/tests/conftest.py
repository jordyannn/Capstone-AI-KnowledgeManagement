import os

# Harus diset sebelum app diimpor: Settings dibaca saat import.
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-0123456789")
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.security import hash_password
from app.main import app
from app.models import Role, User
from app.seed import seed_roles

PASSWORD = "Sandi-Rahasia-123"


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    seed_roles(session)
    yield session
    session.close()


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def make_user(db):
    def _make(email="dosen@example.test", role="dosen", active=True):
        role_row = db.query(Role).filter_by(code=role).one()
        user = User(
            email=email,
            full_name="Pengguna Uji",
            password_hash=hash_password(PASSWORD),
            role_id=role_row.id,
            is_active=active,
        )
        db.add(user)
        db.commit()
        return user

    return _make
