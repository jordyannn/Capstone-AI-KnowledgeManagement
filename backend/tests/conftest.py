import os

# Harus diset sebelum app diimpor: Settings dibaca saat import.
os.environ.setdefault("SECRET_KEY", "test-secret-key-test-secret-key-0123456789")
os.environ.setdefault("DATABASE_URL", "sqlite://")
# SSO di test selalu memakai kredensial palsu, apa pun isi environment (mis. di container yang
# memegang client secret sungguhan). Test tidak boleh pernah menghubungi Microsoft.
os.environ.update(
    SSO_ENABLED="true",
    SSO_CLIENT_ID="test-client-id",
    SSO_CLIENT_SECRET="test-client-secret",
    SSO_TENANT_ID="90affe0f-c2a3-4108-bb98-6ceb4e94ef15",
    SSO_REDIRECT_URI="http://localhost:8080/api/auth/sso/callback",
    SSO_ALLOWED_DOMAINS="telkomuniversity.ac.id,student.telkomuniversity.ac.id",
)

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
def session_factory():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_roles(session)
    yield factory
    engine.dispose()


@pytest.fixture()
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture()
def client(db):
    app.dependency_overrides[get_db] = lambda: db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def make_user(db):
    def _make(email="dosen@example.test", role="dosen", active=True, password=PASSWORD, external_id=None):
        role_row = db.query(Role).filter_by(code=role).one()
        user = User(
            email=email,
            full_name="Pengguna Uji",
            password_hash=hash_password(password) if password else None,
            auth_provider="local" if password else "microsoft",
            external_id=external_id,
            role_id=role_row.id,
            is_active=active,
        )
        db.add(user)
        db.commit()
        return user

    return _make
