from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.main import app
from app.database import get_session


def test_health_checks_database():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    def session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    try:
        response = TestClient(app).get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok", "database": "ok"}
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_health_returns_503_without_database_details():
    from sqlalchemy.exc import OperationalError
    class Unavailable:
        def execute(self, statement):
            raise OperationalError("SELECT 1", {}, Exception("internal connection details"))
    def session():
        yield Unavailable()
    app.dependency_overrides[get_session] = session
    try:
        response = TestClient(app).get("/health")
        assert response.status_code == 503
        assert response.json() == {"status": "error", "database": "unavailable"}
        assert "internal connection details" not in response.text
    finally:
        app.dependency_overrides.clear()
