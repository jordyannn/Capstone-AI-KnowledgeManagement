from sqlalchemy.exc import OperationalError


def test_health_ok_when_postgres_and_chroma_up(client, monkeypatch):
    monkeypatch.setattr("app.api.health.check_chroma", lambda: True)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "postgres": "ok", "chromadb": "ok"}


def test_health_503_when_chroma_down(client, monkeypatch):
    monkeypatch.setattr("app.api.health.check_chroma", lambda: False)
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "postgres": "ok", "chromadb": "down"}


def test_health_503_when_postgres_down(client, db, monkeypatch):
    monkeypatch.setattr("app.api.health.check_chroma", lambda: True)

    def boom(*args, **kwargs):
        raise OperationalError("SELECT 1", {}, Exception("db mati"))

    monkeypatch.setattr(db, "execute", boom)
    r = client.get("/api/health")
    assert r.status_code == 503
    assert r.json() == {"status": "degraded", "postgres": "down", "chromadb": "ok"}
