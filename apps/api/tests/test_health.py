from fastapi.testclient import TestClient

from app.dependencies import get_engine
from app.main import app


def test_health_ok_when_database_reachable():
    client = TestClient(app)

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "generate-web-ai-api"
    assert body["dependencies"]["database"]["status"] == "ok"
    assert "uptime_seconds" in body
    assert "timestamp" in body


def test_health_degraded_when_database_unreachable():
    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("could not connect to database: postgres.railway.internal unreachable")

    app.dependency_overrides[get_engine] = lambda: _BrokenEngine()
    try:
        client = TestClient(app)
        response = client.get("/health")

        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "degraded"
        assert body["dependencies"]["database"]["status"] == "error"
    finally:
        app.dependency_overrides.clear()


def test_health_never_exposes_raw_exception_details_publicly():
    """A6.1: /health is public and unauthenticated — a raw SQLAlchemy/
    driver exception (which can name an internal hostname) must never
    reach the response body, only the server-side log."""

    class _BrokenEngine:
        def connect(self):
            raise RuntimeError("could not connect to database: postgres.railway.internal unreachable")

    app.dependency_overrides[get_engine] = lambda: _BrokenEngine()
    try:
        client = TestClient(app)
        response = client.get("/health")

        assert "detail" not in response.json()["dependencies"]["database"]
        assert "postgres.railway.internal" not in response.text
        assert "could not connect" not in response.text
    finally:
        app.dependency_overrides.clear()
