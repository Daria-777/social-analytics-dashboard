import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from app.database import get_session
from app.main import app
from app.models import Base


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INTERNAL_API_KEY", "test-only-key")
    test_url = os.environ.get("TEST_DATABASE_URL")
    if test_url:
        from tests.postgres_support import test_engine
        engine = test_engine()
        connection = engine.connect()
        transaction = connection.begin()
    else:
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if not test_url:
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)
    def session():
        with Session(connection, join_transaction_mode="create_savepoint") if test_url else Session(engine) as db:
            yield db
    app.dependency_overrides[get_session] = session
    with TestClient(app, headers={"X-API-Key": "test-only-key"}) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    if test_url:
        transaction.rollback()
        connection.close()
    engine.dispose()


@pytest.fixture
def content(client):
    account = client.post("/accounts", json={"platform": "tiktok", "username": "demo.account", "platform_account_id": "test-account"})
    assert account.status_code == 201
    response = client.post("/content", json={"account_id": account.json()["id"], "platform": "tiktok", "platform_content_id": "test-video", "content_type": "video"})
    assert response.status_code == 201
    return response.json()


@pytest.fixture(autouse=True)
def isolate_external_credentials_and_http(monkeypatch):
    from app.config import Settings
    import httpx
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for key in tuple(os.environ):
        if key.startswith(("INSTAGRAM_", "TIKTOK_")):
            monkeypatch.delenv(key, raising=False)
    def no_network(*args, **kwargs):
        raise AssertionError("Tests must use MockTransport; external HTTP is forbidden")
    monkeypatch.setattr(httpx.HTTPTransport,"handle_request",no_network)
    monkeypatch.setenv("INSTAGRAM_EXPECTED_USERNAME", "demo.account")
    monkeypatch.setenv("TIKTOK_EXPECTED_USERNAME", "demo.account")
